# -*- coding: utf-8 -*-
"""
雪团 · 桌面伴侣 v2（macOS 原生，轻量，不依赖 Electron）

双窗口架构：
  场景窗(scene)  全屏、桌面层(壁纸之上/图标之下)、忽略鼠标 → 纯视频壁纸，图标照常可见可点
  宠物窗(pet)    左 40% 透明条、浮在图标之上、可点 → 猫热区 + 指令栏 + 聊天 + 麦克风

指令：整理桌面 / 打开 <应用> / 现在几点 / 笑话 / 其它→DeepSeek 聊天
桌面整理严守：只读扫描 → 列清单 → 用户确认 → 备份清单 → 分批移动(≤10) → 绝不删除

历史踩坑（勿回退）：
- 方法名不能叫 reply / focusApp:（撞 NSObject 选择器 → BadPrototypeError），逻辑一律放类外
- 桌面层窗口收不到点击（Finder 吞掉），可点元素必须单独开浮在图标之上的窗口
- 无边框 NSWindow 默认 canBecomeKeyWindow=False → 必须子类覆写，指令栏才能输入
"""
import os, sys, json, re, shutil, subprocess, tempfile, datetime, argparse, time, threading, urllib.request, random

import objc
from AppKit import (
    NSApplication, NSWindow, NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSScreen, NSColor, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular,
    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorFullScreenAuxiliary, NSFloatingWindowLevel, NSApp)
from WebKit import WKWebView, WKWebViewConfiguration, WKUserContentController
from Foundation import NSURL, NSObject

# ---------- 日志（.app 由 Finder 启动、没有终端，print 全进虚空，必须落文件才能诊断） ----------
_LOG_PATH = os.path.expanduser("~/Library/Logs/xuetuan.log")


def log(msg):
    try:
        d = os.path.dirname(_LOG_PATH)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except Exception:
        pass


def _as_dict(raw):
    """WKScriptMessage.body() 在 pyobjc 里是【Objective-C 的 NSDictionary】，
    不是 Python dict —— isinstance(body, dict) 恒为 False，
    会导致所有 JS→原生 消息被当成「非法」静默丢弃（点击/聊天/麦克风全失效）。
    这里统一转成 Python dict。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:                                  # NSDictionary
        out = {}
        for k in raw.allKeys():
            v = raw.objectForKey_(k)
            out[str(k)] = v
        return out
    except Exception:
        pass
    try:
        return dict(raw)
    except Exception:
        return {}


# ---------- 卡通嗓音（say 合成 → 改采样率标签升调 → afplay 播放）----------
# 为什么不用 ffmpeg：本机没装。改 WAV 头里的采样率数字即可「升调 + 加速」，
# 再把 say 的基础语速调慢来抵消加速，净效果 = 音调变高、语速正常 → 奶音卡通感。
TTS_PITCH = 1.26          # 音调倍数（>1 更尖细）
TTS_RATE = 168            # say 基础语速（词/分）；净值 ≈ TTS_RATE * TTS_PITCH
_tts = {"on": False, "proc": None, "voice": None,
        "speaking": False, "last_text": "", "last_end": 0.0}
_nap = {"on": False}                 # 猫小睡状态（😴 休息按钮）

# 需要念出来的回传类型（progress/scan/transcript/chatdelta 这类不念）
# chatend 才是完整一句，流式中间片段 chatdelta 不念，否则会结巴
_SPEAK_TYPES = ("chat", "chatend", "time", "joke", "open", "done", "help", "remind", "mem")


def _pick_voice():
    """按当前语言挑嗓音：中文 Ting-Ting、英语 Samantha、日语 Kyoko…（缺哪个就顺位往下找）。"""
    if _tts.get("voice"):
        return _tts["voice"]
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True,
                             text=True, timeout=10).stdout or ""
    except Exception as e:
        log("列语音失败: " + repr(e))
        return None
    have = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 2:
            have[p[0]] = p[1]
    for name in L().get("voices", []):
        if name in have:
            _tts["voice"] = name
            log("选中嗓音[%s]: %s" % (_lang["now"], name))
            return name
    # 语言包里的都没装 → 退到该语言的任意一个同名 locale 嗓音
    want = (L().get("locales") or [""])[0].replace("-", "_").lower()
    for n, loc in have.items():
        if loc.lower() == want:
            _tts["voice"] = n
            log("回退嗓音: " + n)
            return n
    return None


def _clean_for_speech(t):
    """把文字洗成适合朗读的样子：去旁白括号、markdown、表情符号。"""
    t = re.sub(r"[（(][^）)]{0,40}[）)]", "", t)          # 去掉（旁白/备注）
    t = re.sub(r"[*_`#>~\[\]]", "", t)                  # markdown 符号
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF]", "", t)  # emoji
    t = re.sub(r"\s+", " ", t).strip()
    return t


def stop_speak():
    p = _tts.get("proc")
    if p is not None:
        try:
            p.terminate()
        except Exception:
            pass
    _tts["proc"] = None


_tts_seq = [0]
_tts_lock = threading.Lock()


def speak(text):
    """后台线程合成并播放，不阻塞界面。"""
    if not _tts.get("on") or not text:
        return
    text = _clean_for_speech(str(text))
    if not text:
        return
    # 长回答念到句子边界为止，别从半句话中间腰斩
    if len(text) > 400:
        cut = max(text.rfind("。", 0, 400), text.rfind(". ", 0, 400),
                  text.rfind("！", 0, 400), text.rfind("？", 0, 400))
        text = text[:cut + 1] if cut > 120 else text[:400]
    stop_speak()                      # 新一句来了，先打断上一句
    with _tts_lock:
        _tts_seq[0] += 1
        tag = "%d_%d" % (os.getpid(), _tts_seq[0])

    def work():
        # 踩过的坑：早先用固定文件名 xuetuan_say.aiff，连着说两句时
        # 第二个线程会把第一个还没转完的文件覆盖掉 → 爆音或直接报错。
        # 每句用自己的临时文件，播完删掉。
        aiff = wav = wav2 = None
        try:
            import wave
            d = tempfile.gettempdir()
            aiff = os.path.join(d, "xt_%s.aiff" % tag)
            wav = os.path.join(d, "xt_%s.wav" % tag)
            wav2 = os.path.join(d, "xt_%s_p.wav" % tag)
            cmd = ["say", "-r", str(TTS_RATE)]
            v = _pick_voice()
            if v:
                cmd += ["-v", v]
            cmd += ["-o", aiff, text]
            subprocess.run(cmd, timeout=40, check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", aiff, wav],
                           timeout=20, check=True)
            with wave.open(wav, "rb") as w:
                pm = w.getparams()
                frames = w.readframes(w.getnframes())
            nr = int(pm.framerate * TTS_PITCH)         # 只改标签 → 升调 + 加速
            with wave.open(wav2, "wb") as o:
                o.setparams((pm.nchannels, pm.sampwidth, nr, 0, "NONE", ""))
                o.writeframes(frames)
            _tts["last_text"] = text
            _mic_hold()                       # 开口前先捂住自己的耳朵
            _tts["speaking"] = True
            push_js(_KEEP.get("handler"), {"type": "speakstate", "on": True})
            proc = subprocess.Popen(["afplay", wav2])
            _tts["proc"] = proc
            proc.wait()
            log("TTS 播放完成（%d 字）" % len(text))
        except Exception as e:
            log("TTS 失败: " + repr(e))
        finally:
            _tts["speaking"] = False
            _tts["last_end"] = time.time()
            try:
                push_js(_KEEP.get("handler"), {"type": "speakstate", "on": False})
            except Exception:
                pass
            _mic_release()                    # 说完把耳朵还回来
            for f in (aiff, wav, wav2):
                try:
                    if f and os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass
    threading.Thread(target=work, daemon=True).start()


def set_tts(on, h=None, notify=False):
    _tts["on"] = bool(on)
    if not _tts["on"]:
        stop_speak()
    log("语音回复 = %s" % _tts["on"])
    _save_conf()
    if notify and h is not None:
        push_js(h, {"type": "ttsstate", "on": _tts["on"],
                    "msg": T("ttsOn" if on else "ttsOff")})


# ---------- 四季背景 ----------
_SEASONS = ["spring", "summer", "autumn", "winter"]
_SEASON_CN = {"spring": "春天", "summer": "夏天", "autumn": "秋天", "winter": "冬天"}
_SEASON_FILE = os.path.expanduser("~/.workbuddy/xuetuan_season.txt")
_season = {"now": "winter"}


def _load_season():
    try:
        with open(_SEASON_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if v in _SEASONS:
            _season["now"] = v
    except Exception:
        pass
    log("当前季节 = " + _season["now"])


def _save_season(v):
    try:
        d = os.path.dirname(_SEASON_FILE)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(_SEASON_FILE, "w", encoding="utf-8") as f:
            f.write(v)
    except Exception as e:
        log("季节保存失败: " + repr(e))


def _push_scene(obj):
    """把消息推给场景窗（它没注册消息桥，只能被推）。"""
    w = _KEEP.get("scene_web")
    if w is None:
        return
    js = "window.onPetResult && onPetResult(" + json.dumps(obj, ensure_ascii=False) + ")"
    try:
        w.evaluateJavaScript_completionHandler_(js, None)
    except Exception as e:
        log("push scene 失败: " + repr(e))


def set_season(name, h=None):
    if name == "next":
        i = _SEASONS.index(_season["now"])
        name = _SEASONS[(i + 1) % len(_SEASONS)]
    if name not in _SEASONS:
        return
    _season["now"] = name
    _save_season(name)
    _save_conf()
    log("切换季节 -> " + name)
    _push_scene({"type": "season", "name": name})          # 场景窗换背景
    if h is not None:                                      # 宠物窗给个回话
        push_js(h, {"type": "season", "name": name,
                    "msg": T("seasonSet", name=L()["seasons"][name])})


# ---------- 猫小睡 / 额外动作 ----------
# 猫本身长在场景视频里，所以「休息」= 场景窗把主视频换成语打哈欠的片子（不再转圈）；
# 「更多动作」= 随机挑一条额外片子盖到场景窗上。两种状态都写盘，重启还在。
_ACTIONS = ["hello", "scenery", "idle"]     # ✨ 随机池；yawn 专给「休息/打哈欠睡觉」用
# 动作名别名。菜单里「打哈欠睡觉」发下来的是 rest，必须翻成 yawn ——
# 不加这张表就会被当成未知名字，落到 random.choice 上：点「打哈欠睡觉」
# 有 2/3 的概率演成「坐着眨眼」，用户看到的就是「有时候不灵」。
_ACT_ALIAS = {"rest": "yawn", "sleep": "yawn", "yawn": "yawn", "nap": "yawn",
              "wave": "hello", "hi": "hello", "hello": "hello",
              "look": "scenery", "scenery": "scenery", "view": "scenery",
              "idle": "idle", "muse": "idle"}
# 每条动作在屏幕上停留多久（毫秒）。scenery/yawn 是「播一遍后定格」，
# 时长要略大于片子本身（3.7s / 5.0s），否则会从半截被掐掉。
_ACT_MS = {"hello": 5000, "scenery": 6200, "idle": 6000, "yawn": 0}


def set_rest(on, h=None):
    _nap["on"] = bool(on)
    _save_conf()
    log("猫小睡 = %s" % _nap["on"])
    msg = T("restOn" if on else "restOff")
    # 场景窗负责换片子（它的 onPetResult 接了 reststate 分支）
    _push_scene({"type": "reststate", "on": _nap["on"], "msg": msg})
    if h is not None:                          # 宠物窗同步按钮 + 气泡
        push_js(h, {"type": "reststate", "on": _nap["on"], "msg": msg})


def _act_line(name):
    """这个动作配哪句台词（按当前语言取）。发呆 = 心理活动，每次随机一句。"""
    ui = L().get("ui") or {}
    if name == "hello":
        return ui.get("actHello")
    if name == "idle":
        m = ui.get("musings") or []
        return random.choice(m) if m else None
    return None


def do_action(h=None, name=None):
    """演一个动作。name 为空 = 随机演一个；给了就演指定的。

    名字认不出来时**绝不**悄悄换成随机动作：那样「打哈欠睡觉」会随机演成
    坐着眨眼，表现成「有时候不灵」。先查别名表，还认不出就当作没指定。"""
    if name:
        name = _ACT_ALIAS.get(str(name), str(name))
        if name not in _ACT_MS:
            log("未知动作名，什么都不演: " + str(name))
            return                      # 认不出来就不演 —— 绝不随机顶替（那正是「点了没反应/演错」的病根）
    else:
        name = random.choice(_ACTIONS)      # 只有真的没指定名字时才随机
    log("触发额外动作: " + name)
    # 片子只有场景窗能放（猫长在场景视频里）
    _push_scene({"type": "act", "name": name, "ms": _ACT_MS.get(name, 4200)})
    # 台词气泡只有宠物窗能显示（场景窗的 #say 是隐藏的），所以走 push_js
    if h is not None:
        line = _act_line(name)
        if line:
            push_js(h, {"type": "bubble", "msg": line,
                        "delay": 1100 if name == "idle" else 0})


# ---------- 多语言 ----------
# 一处定义，四件事同时跟着变：
#   ① 界面文案  ② 卡通嗓音（say 语音）  ③ 语音识别语言（SFSpeechRecognizer locale）
#   ④ 大模型的回答语言 + 系统人设
# 唯一真源在 Python 侧，页面载入时通过 i18n 消息下发，改语言不用重新打包 HTML。
LANGS = {
    "zh": {
        "name": "中文", "voices": ["Ting-Ting", "Tingting", "Mei-Jia", "Sin-ji"],
        "locales": ["zh-CN", "zh-Hans-CN", "zh-TW", "zh-HK", "yue-CN"],
        "sys": ("你是雪团，一只住在用户电脑桌面上的原创卡通猫桌面伴侣，性格温软治愈、偶尔毒舌但很暖心。"
                "你负责陪伴、闲聊、提醒用户休息、讲点冷知识。语气轻松像朋友，不要长篇大论。"
                "重要边界：你不扮演恋人、不做医疗建议、不做投资建议，遇到这类问题委婉带过。"
                "用户是位做投资的 CEO，偶尔焦虑，你用轻松的方式陪他聊聊、帮他减压即可。请用中文回答。"),
        "seasons": {"spring": "春天", "summer": "夏天", "autumn": "秋天", "winter": "冬天"},
        "words": {
            "season": {"春天": "spring", "春日": "spring", "夏天": "summer", "夏日": "summer",
                       "秋天": "autumn", "秋日": "autumn", "落叶": "autumn",
                       "冬天": "winter", "冬日": "winter", "下雪": "winter"},
            "next": ["换季", "下一个季节", "换个季节", "换季节"],
            "help": ["帮助", "能做什么", "会什么", "指令"],
            "tidy": ["整理"], "open": ["打开"], "time": ["几点", "时间"], "joke": ["笑话"],
        },
        "jokes": ["为什么猫不用电脑？——怕被说是「鼠标」。【雪团】",
                  "投资最稳的标的，是你今晚早点睡。【雪团】",
                  "雪团守则第一条：盯盘可以，别盯到忘记我。【雪团】"],
        "ui": {
            "hint": "点雪团说话 · 试试「整理桌面」「打开 Safari」「现在几点」或随便聊",
            "ph": "对雪团说点什么…（回车发送）", "thinking": "雪团在想…", "listening": "喵～我在听，说吧",
            "heard": "听到了，按回车发给我（想改也行）",
            "ttsOn": "好～我用声音陪你说话", "ttsOff": "好，我只打字", "restOn": "好～我先眯一会", "restOff": "醒啦！陪你玩", "actHello": "喵～你好呀！我一直在这儿呢", "musings": ["……这场雪要是一直下，我就一直看下去", "一个很严肃的问题：小鱼干到底算不算正餐", "外面那盏灯今天好像亮得早了点", "刚才那个哈欠，其实我是装的"], "micFail": "没听清，再说一次？",
            "acts": {"hello": ["👋", "招手问候"], "scenery": ["🌄", "看风景"],
                     "idle": ["😌", "发个呆"], "rest": ["🥱", "打哈欠睡觉"]},
            "seasonSet": "换成{name}啦～", "langSet": "好，我们换成{name}聊～",
            "timeNow": "现在 {t}，记得起来活动一下～",
            "openOk": "已帮你打开 {app}", "openNone": "没听清要打开什么",
            "tidyEmpty": "桌面已经是空的，没什么可整理～",
            "tidyBusy": "上一轮整理还没结束，先等一下～",
            "planTitle": "整理桌面预览", "planSub": "下面是会动的文件（只读扫描结果，还没动任何东西）",
            "planWarn": "⚠️ 确认后我会把零散文件按类型搬进「雪团归档_时间戳」文件夹，不会删除任何文件，并留清单可一键还原。",
            "planOk": "确认整理", "planNo": "取消",
            "tidyDone": "共搬动 {n} 个文件到\n{p}\n（清单在 _manifest.txt，随时可还原，未删除任何文件）",
            "undoDone": "已经把 {n} 个文件放回桌面啦", "undoNone": "没找到可以撤销的归档",
            "remindSet": "好，{t}后提醒你：{w}", "remindFire": "⏰ 时间到啦：{w}",
            "remindNone": "（雪团提醒）", "remindAsk": "好，10 分钟后提醒你：{w}",
            "rest": "你已经盯了 {m} 分钟啦，起来走两步、看看远处，我在这儿等你～",
            "memName": "记住啦，以后我叫你 {name}", "memAdd": "记住了：{f}",
            "memForget": "好，我把记的东西都忘掉啦", "memWho": "你叫 {name} 呀",
            "memNoName": "你还没告诉我名字呢，说「我叫某某」我就记住了",
            "noKey": "（雪团还没接上 DeepSeek：把 key 写进 ~/.workbuddy/deepseek.key 就能跟我真聊啦）",
            "netErr": "雪团刚才走神了，再说一次？",
            "micNeed": "正在申请麦克风与语音识别权限，请在弹窗里点「好」…",
            "micDenied": "权限曾被拒绝，系统不会再弹窗。已帮你打开设置页：麦克风 与 语音识别 里勾上「雪团」",
            "micNoPopup": "权限弹窗没出现（{s} 秒无响应）。已打开设置页，请手动勾上「雪团」",
            "micOk": "在听，说吧～", "micStop": "不听了",
            "micHold": "（雪团说话中，先不听了）",
            "micAsset": "{lang}语音资源未安装：系统设置→键盘→听写，打开后选「{lang}」会自动下载",
            "micUnavail": "当前语音识别不可用（可能离线/区域不支持）",
            "chips": ["整理桌面", "现在几点", "讲个笑话"],
            "help": ("我能做这些：\n· 说「整理」→ 我先列清单给你确认，绝不乱动文件\n"
                     "· 说「打开 Safari」「现在几点」「讲个笑话」\n"
                     "· 说「春天/夏天/秋天/冬天」换背景，或「换季」\n"
                     "· 说「10 分钟后提醒我喝水」→ 到点我叫你\n"
                     "· 说「我叫 Bill」「记住我不喝咖啡」→ 我会一直记得\n"
                     "· 点 🎤 说话，说完回车发给我；点 🔊 我念给你听；点 🌐 换语言\n"
                     "· 其他随便聊，我陪你"),
        },
    },
    "en": {
        "name": "English", "voices": ["Samantha", "Ava", "Karen", "Daniel"],
        "locales": ["en-US", "en_US", "en-GB", "en-AU"],
        "sys": ("You are Xuetuan (雪团), an original cartoon cat who lives on the user's desktop. "
                "Warm, gently snarky, calming. You keep him company, chat, remind him to rest, and drop "
                "fun facts. Talk like a friend, keep it short. Boundaries: never roleplay as a lover, "
                "never give medical or investment advice — sidestep those kindly. The user is a CEO who "
                "invests and gets anxious sometimes; help him decompress. Reply in English."),
        "seasons": {"spring": "Spring", "summer": "Summer", "autumn": "Autumn", "winter": "Winter"},
        "words": {
            "season": {"spring": "spring", "summer": "summer", "autumn": "autumn", "fall": "autumn",
                       "winter": "winter", "snow": "winter"},
            "next": ["next season", "change season", "switch season"],
            "help": ["help", "what can you do", "commands"],
            "tidy": ["tidy", "clean", "organi"], "open": ["open"], "time": ["time", "clock"], "joke": ["joke", "funny"],
        },
        "jokes": ["Why don't cats use computers? They're afraid of being called a mouse. —Xuetuan",
                  "The safest investment tonight is eight hours of sleep. —Xuetuan",
                  "Rule #1: you may watch the market, but never forget to watch me. —Xuetuan"],
        "ui": {
            "hint": "Click the cat · try \"tidy desk\", \"open Safari\", \"what time\" — or just chat",
            "ph": "Say something to Xuetuan… (Enter to send)", "thinking": "Thinking…",
            "listening": "Meow~ I'm listening", "heard": "Got it — press Enter to send (or edit it first)",
            "ttsOn": "Okay, I'll talk out loud", "ttsOff": "Okay, typing only", "restOn": "Okay, I'll nap a bit", "restOff": "Awake! Back to play", "actHello": "Meow~ hello there! I'm right here", "musings": ["...if the snow keeps falling, I'm staying right here", "Serious question: do fish snacks count as a meal?", "That lamp outside lit up a little early tonight", "That yawn earlier? Completely staged"], "micFail": "Didn't catch that — say it again?",
            "acts": {"hello": ["👋", "Wave hello"], "scenery": ["🌄", "Watch the view"],
                     "idle": ["😌", "Just chill"], "rest": ["🥱", "Yawn & sleep"]},
            "seasonSet": "Switched to {name}~", "langSet": "Sure, let's talk in {name}~",
            "timeNow": "It's {t} — time to stretch a little",
            "openOk": "Opened {app}", "openNone": "Didn't catch what to open",
            "tidyEmpty": "Your desktop is already clean~",
            "tidyBusy": "Still tidying, give me a moment.",
            "planTitle": "Tidy preview", "planSub": "Files that would move (read-only scan — nothing touched yet)",
            "planWarn": "⚠️ After you confirm I move loose files into a \"xuetuan archive\" folder by type. Nothing is deleted and a manifest lets you undo it.",
            "planOk": "Confirm", "planNo": "Cancel",
            "tidyDone": "Moved {n} files into\n{p}\n(manifest inside — nothing was deleted)",
            "undoDone": "Put {n} files back on your desktop", "undoNone": "No archive to undo",
            "remindSet": "Got it — I'll remind you in {t}: {w}", "remindFire": "⏰ Time's up: {w}",
            "remindNone": "(a reminder)", "remindAsk": "Okay, 10 minutes then: {w}",
            "rest": "You've been at it for {m} minutes — stand up, look far away. I'll wait here~",
            "memName": "Got it, I'll call you {name}", "memAdd": "Remembered: {f}",
            "memForget": "Forgot everything~", "memWho": "You're {name}",
            "memNoName": "You haven't told me your name — say \"call me …\"",
            "noKey": "(Xuetuan isn't connected to DeepSeek yet: drop your key in ~/.workbuddy/deepseek.key)",
            "netErr": "I spaced out — say that again?",
            "micNeed": "Asking for mic + speech permission — click OK in the popup…",
            "micDenied": "Permission was denied before. Opened System Settings: tick Xuetuan under Microphone and Speech Recognition",
            "micNoPopup": "No popup after {s}s. Opened System Settings — please tick Xuetuan manually",
            "micOk": "Listening~", "micStop": "Stopped listening",
            "micHold": "(Xuetuan is talking — mic paused)",
            "micAsset": "{lang} speech assets missing: System Settings → Keyboard → Dictation, turn it on to download",
            "micUnavail": "Speech recognition unavailable right now (offline / region)",
            "chips": ["Tidy desk", "What time", "Tell a joke"],
            "help": ("Here's what I do:\n· \"tidy\" → I list everything first and never touch a file without your OK\n"
                     "· \"open Safari\", \"what time\", \"tell a joke\"\n"
                     "· \"spring/summer/autumn/winter\" to change the scene, or \"next season\"\n"
                     "· \"remind me to drink water in 10 minutes\"\n"
                     "· \"call me Bill\" / \"remember I don't drink coffee\" → I'll keep it\n"
                     "· 🎤 to talk, Enter to send · 🔊 to hear me · 🌐 to switch language\n"
                     "· anything else — I'll just chat"),
        },
    },
    "es": {
        "name": "Español", "voices": ["Monica", "Paulina", "Jorge", "Juan"],
        "locales": ["es-ES", "es_MX", "es-419", "es-US"],
        "sys": ("Eres Xuetuan (雪团), un gato de dibujos original que vive en el escritorio del usuario. "
                "Cálido, con ironía suave y muy tranquilizador. Acompañas, charlas, recuerdas descansar y "
                "cuentas datos curiosos. Habla como un amigo, sin rollos largos. Límites: nunca interpretes "
                "a una pareja, nunca des consejos médicos ni de inversión; esquívalos con cariño. El usuario "
                "es un CEO que invierte y a veces se angustia: ayúdale a desconectar. Responde en español."),
        "seasons": {"spring": "Primavera", "summer": "Verano", "autumn": "Otoño", "winter": "Invierno"},
        "words": {
            "season": {"primavera": "spring", "verano": "summer", "otoño": "autumn", "otono": "autumn",
                       "invierno": "winter", "nieve": "winter"},
            "next": ["siguiente estación", "cambia estación", "cambiar estación", "otra estación"],
            "help": ["ayuda", "qué puedes hacer"],
            "tidy": ["ordenar", "limpiar", "organizar"], "open": ["abre", "abrir"],
            "time": ["hora", "qué hora"], "joke": ["chiste", "broma"],
        },
        "jokes": ["¿Por qué los gatos no usan ordenador? Por miedo a que les llamen «ratón». —Xuetuan",
                  "La inversión más segura de esta noche: ocho horas de sueño. —Xuetuan",
                  "Norma 1: puedes mirar el mercado, pero nunca olvides mirarme a mí. —Xuetuan"],
        "ui": {
            "hint": "Toca al gato · prueba «ordenar escritorio», «abre Safari», «qué hora» o charla",
            "ph": "Dile algo a Xuetuan… (Enter para enviar)", "thinking": "Pensando…",
            "listening": "Miau~ te escucho", "heard": "Listo — pulsa Enter para enviar (o edítalo)",
            "ttsOn": "Vale, te hablo en voz alta", "ttsOff": "Vale, solo escribo", "restOn": "Vale, echa una siesta", "restOff": "¡Despierta! Volvamos a jugar", "actHello": "¡Miau~ hola! Aquí estoy", "musings": ["...si sigue nevando, me quedo mirando", "Pregunta seria: ¿las golosinas de pescado cuentan como comida?", "Esa lámpara de fuera se encendió antes hoy", "Ese bostezo de antes lo hice a propósito"], "micFail": "No te entendí, ¿lo repites?",
            "acts": {"hello": ["👋", "Saludar"], "scenery": ["🌄", "Ver el paisaje"],
                     "idle": ["😌", "Relajarse"], "rest": ["🥱", "Bostezar y dormir"]},
            "seasonSet": "Cambiado a {name}~", "langSet": "Claro, hablemos en {name}~",
            "timeNow": "Son las {t} — muévete un poco",
            "openOk": "He abierto {app}", "openNone": "No entendí qué abrir",
            "tidyEmpty": "El escritorio ya está limpio~",
            "tidyBusy": "Todavía estoy ordenando, espera un momento.",
            "planTitle": "Vista previa", "planSub": "Archivos que se moverían (solo lectura, aún no tocamos nada)",
            "planWarn": "⚠️ Al confirmar moveré los archivos sueltos a una carpeta de archivo por tipo. No borro nada y dejo un listado para deshacerlo.",
            "planOk": "Confirmar", "planNo": "Cancelar",
            "tidyDone": "Moví {n} archivos a\n{p}\n(hay un listado dentro, no se borró nada)",
            "undoDone": "Devolví {n} archivos al escritorio", "undoNone": "No hay archivo que deshacer",
            "remindSet": "Vale, te aviso en {t}: {w}", "remindFire": "⏰ Es la hora: {w}",
            "remindNone": "(un recordatorio)", "remindAsk": "Vale, en 10 minutos: {w}",
            "rest": "Llevas {m} minutos ahí — levántate y mira lejos. Te espero aquí~",
            "memName": "Anotado, te llamo {name}", "memAdd": "Recordado: {f}",
            "memForget": "Olvidado todo~", "memWho": "Te llamas {name}",
            "memNoName": "No me has dicho tu nombre — di «me llamo …»",
            "noKey": "(Xuetuan aún no está conectado a DeepSeek: pon tu clave en ~/.workbuddy/deepseek.key)",
            "netErr": "Me despisté un segundo, ¿lo repites?",
            "micNeed": "Pidiendo permisos de micro y voz — pulsa Aceptar…",
            "micDenied": "El permiso se denegó antes. Abrí Ajustes: marca Xuetuan en Micrófono y Reconocimiento de voz",
            "micNoPopup": "Sin aviso tras {s}s. Abrí Ajustes — marca Xuetuan a mano",
            "micOk": "Escuchando~", "micStop": "Dejo de escuchar",
            "micHold": "(Xuetuan está hablando — micro en pausa)",
            "micAsset": "Faltan recursos de voz en {lang}: Ajustes → Teclado → Dictado, actívalo para descargar",
            "micUnavail": "Reconocimiento de voz no disponible ahora (sin conexión o región)",
            "chips": ["Ordenar", "Qué hora", "Un chiste"],
            "help": ("Esto sé hacer:\n· «ordenar» → te listo todo antes y no toco nada sin tu OK\n"
                     "· «abre Safari», «qué hora», «un chiste»\n"
                     "· «primavera/verano/otoño/invierno» para cambiar el fondo, o «siguiente estación»\n"
                     "· «recuérdame beber agua en 10 minutos»\n"
                     "· «me llamo Bill» / «recuerda que no tomo café» → lo guardo\n"
                     "· 🎤 para hablar, Enter para enviar · 🔊 para oírme · 🌐 para cambiar idioma"),
        },
    },
    "fr": {
        "name": "Français", "voices": ["Thomas", "Amelie", "Audrey"],
        "locales": ["fr-FR", "fr_CA", "fr-CH"],
        "sys": ("Tu es Xuetuan (雪团), un chat de dessin animé original qui vit sur le bureau de l'utilisateur. "
                "Chaleureux, un brin moqueur, apaisant. Tu tiens compagnie, discutes, rappelles de se reposer et "
                "partages des anecdotes. Parle comme un ami, reste bref. Limites : jamais de rôle de partenaire, "
                "jamais de conseil médical ou d'investissement — élude-les gentiment. L'utilisateur est un PDG qui "
                "investit et s'angoisse parfois ; aide-le à décompresser. Réponds en français."),
        "seasons": {"spring": "Printemps", "summer": "Été", "autumn": "Automne", "winter": "Hiver"},
        "words": {
            "season": {"printemps": "spring", "été": "summer", "ete": "summer", "automne": "autumn",
                       "hiver": "winter", "neige": "winter"},
            "next": ["saison suivante", "change de saison", "autre saison"],
            "help": ["aide", "que peux-tu faire"],
            "tidy": ["ranger", "nettoyer", "organiser"], "open": ["ouvre", "ouvrir"],
            "time": ["heure", "quelle heure"], "joke": ["blague", "humour"],
        },
        "jokes": ["Pourquoi les chats n'utilisent pas d'ordinateur ? Ils ont peur qu'on les appelle « souris ». —Xuetuan",
                  "Le placement le plus sûr ce soir : huit heures de sommeil. —Xuetuan",
                  "Règle n°1 : tu peux surveiller le marché, mais n'oublie pas de me regarder. —Xuetuan"],
        "ui": {
            "hint": "Clique sur le chat · essaie « ranger le bureau », « ouvre Safari », « quelle heure »",
            "ph": "Dis quelque chose à Xuetuan… (Entrée pour envoyer)", "thinking": "Je réfléchis…",
            "listening": "Miaou~ je t'écoute", "heard": "Reçu — Entrée pour envoyer (ou corrige)",
            "ttsOn": "D'accord, je te parle à voix haute", "ttsOff": "D'accord, j'écris seulement", "restOn": "D'accord, je fais la sieste", "restOff": "Réveillé ! On joue", "actHello": "Miaou~ bonjour ! Je suis là", "musings": ["...s'il continue de neiger, je reste ici", "Question sérieuse : les friandises au poisson, ça compte comme un repas ?", "Cette lampe dehors s'est allumée un peu tôt ce soir", "Ce bâillement tout à l'heure ? C'était du cinéma"], "micFail": "Je n'ai pas compris, tu répètes ?",
            "acts": {"hello": ["👋", "Dire bonjour"], "scenery": ["🌄", "Voir le paysage"],
                     "idle": ["😌", "Se détendre"], "rest": ["🥱", "Bâiller et dormir"]},
            "seasonSet": "Passé à {name}~", "langSet": "D'accord, parlons en {name}~",
            "timeNow": "Il est {t} — bouge un peu",
            "openOk": "J'ai ouvert {app}", "openNone": "Je n'ai pas compris quoi ouvrir",
            "tidyEmpty": "Le bureau est déjà propre~",
            "tidyBusy": "Je range encore, attends un instant.",
            "planTitle": "Aperçu du rangement", "planSub": "Fichiers qui bougeraient (scan lecture seule, rien touché)",
            "planWarn": "⚠️ Après confirmation je déplace les fichiers épars dans un dossier d'archive par type. Rien n'est supprimé et un manifeste permet d'annuler.",
            "planOk": "Confirmer", "planNo": "Annuler",
            "tidyDone": "J'ai déplacé {n} fichiers dans\n{p}\n(manifeste à l'intérieur, rien supprimé)",
            "undoDone": "J'ai remis {n} fichiers sur le bureau", "undoNone": "Aucune archive à annuler",
            "remindSet": "Compris — je te rappelle dans {t} : {w}", "remindFire": "⏰ C'est l'heure : {w}",
            "remindNone": "(un rappel)", "remindAsk": "D'accord, dans 10 minutes : {w}",
            "rest": "Ça fait {m} minutes — lève-toi, regarde au loin. Je t'attends ici~",
            "memName": "Noté, je t'appelle {name}", "memAdd": "Retenu : {f}",
            "memForget": "Tout oublié~", "memWho": "Tu t'appelles {name}",
            "memNoName": "Tu ne m'as pas dit ton nom — dis « je m'appelle … »",
            "noKey": "(Xuetuan n'est pas encore relié à DeepSeek : mets ta clé dans ~/.workbuddy/deepseek.key)",
            "netErr": "J'ai décroché une seconde, tu répètes ?",
            "micNeed": "Demande d'accès micro et voix — clique OK…",
            "micDenied": "Accès refusé avant. Réglages ouverts : coche Xuetuan dans Micro et Reconnaissance vocale",
            "micNoPopup": "Aucun message après {s}s. Réglages ouverts — coche Xuetuan à la main",
            "micOk": "J'écoute~", "micStop": "J'arrête d'écouter",
            "micHold": "(Xuetuan parle — micro en pause)",
            "micAsset": "Ressources vocales {lang} manquantes : Réglages → Clavier → Dictée, active pour télécharger",
            "micUnavail": "Reconnaissance vocale indisponible (hors ligne ou région)",
            "chips": ["Ranger", "Quelle heure", "Une blague"],
            "help": ("Voilà ce que je sais faire :\n· « ranger » → je liste tout d'abord et ne touche à rien sans ton OK\n"
                     "· « ouvre Safari », « quelle heure », « une blague »\n"
                     "· « printemps/été/automne/hiver » pour changer le décor, ou « saison suivante »\n"
                     "· « rappelle-moi de boire dans 10 minutes »\n"
                     "· « je m'appelle Bill » / « retiens que je ne bois pas de café » → je m'en souviens\n"
                     "· 🎤 pour parler, Entrée pour envoyer · 🔊 pour m'entendre · 🌐 pour changer de langue"),
        },
    },
    "pt": {
        "name": "Português", "voices": ["Luciana", "Joana", "Felipe"],
        "locales": ["pt-BR", "pt_BR", "pt-PT"],
        "sys": ("Você é Xuetuan (雪团), um gato de desenho original que vive na área de trabalho do usuário. "
                "Acolhedor, levemente irônico e calmante. Faz companhia, conversa, lembra de descansar e conta "
                "curiosidades. Fale como um amigo, seja breve. Limites: nunca finja ser um parceiro amoroso, "
                "nunca dê conselhos médicos ou de investimento — desvie com carinho. O usuário é um CEO que "
                "investe e às vezes fica ansioso; ajude-o a relaxar. Responda em português."),
        "seasons": {"spring": "Primavera", "summer": "Verão", "autumn": "Outono", "winter": "Inverno"},
        "words": {
            "season": {"primavera": "spring", "verão": "summer", "verao": "summer", "outono": "autumn",
                       "inverno": "winter", "neve": "winter"},
            "next": ["próxima estação", "proxima estacao", "trocar estação", "mudar estação"],
            "help": ["ajuda", "o que você faz"],
            "tidy": ["organizar", "limpar", "arrumar"], "open": ["abra", "abrir"],
            "time": ["hora", "que horas"], "joke": ["piada", "engraçado"],
        },
        "jokes": ["Por que os gatos não usam computador? Medo de serem chamados de «mouse». —Xuetuan",
                  "O investimento mais seguro hoje: oito horas de sono. —Xuetuan",
                  "Regra 1: você pode olhar o mercado, mas nunca esqueça de me olhar. —Xuetuan"],
        "ui": {
            "hint": "Clique no gato · tente «organizar a mesa», «abra o Safari», «que horas»",
            "ph": "Diga algo ao Xuetuan… (Enter envia)", "thinking": "Pensando…",
            "listening": "Miau~ estou ouvindo", "heard": "Pronto — Enter envia (ou edite antes)",
            "ttsOn": "Ok, vou falar em voz alta", "ttsOff": "Ok, só escrevo", "restOn": "Ok, vou tirar uma soneca", "restOff": "Acordei! Bora brincar", "actHello": "Miau~ olá! Estou aqui", "musings": ["...se continuar nevando, fico aqui olhando", "Pergunta séria: petisco de peixe conta como refeição?", "Aquela lâmpada lá fora acendeu mais cedo hoje", "Aquele bocejo de antes? Foi encenação"], "micFail": "Não entendi, repete?",
            "acts": {"hello": ["👋", "Dar oi"], "scenery": ["🌄", "Ver a paisagem"],
                     "idle": ["😌", "Relaxar"], "rest": ["🥱", "Bocejar e dormir"]},
            "seasonSet": "Mudou para {name}~", "langSet": "Claro, vamos falar em {name}~",
            "timeNow": "São {t} — levante-se um pouco",
            "openOk": "Abri {app}", "openNone": "Não entendi o que abrir",
            "tidyEmpty": "A mesa já está limpa~",
            "tidyBusy": "Ainda estou organizando, espera um pouco.",
            "planTitle": "Prévia da organização", "planSub": "Arquivos que seriam movidos (só leitura, nada mexido ainda)",
            "planWarn": "⚠️ Ao confirmar eu movo os arquivos soltos para uma pasta de arquivo por tipo. Nada é apagado e há um manifesto para desfazer.",
            "planOk": "Confirmar", "planNo": "Cancelar",
            "tidyDone": "Movi {n} arquivos para\n{p}\n(há um manifesto dentro, nada foi apagado)",
            "undoDone": "Devolvi {n} arquivos para a mesa", "undoNone": "Sem arquivo para desfazer",
            "remindSet": "Ok, te lembro em {t}: {w}", "remindFire": "⏰ Deu a hora: {w}",
            "remindNone": "(um lembrete)", "remindAsk": "Ok, em 10 minutos: {w}",
            "rest": "Você está nisso há {m} minutos — levante, olhe longe. Espero aqui~",
            "memName": "Anotado, te chamo de {name}", "memAdd": "Lembrado: {f}",
            "memForget": "Esqueci tudo~", "memWho": "Você se chama {name}",
            "memNoName": "Você não me disse seu nome — diga «meu nome é …»",
            "noKey": "(Xuetuan ainda não está ligado ao DeepSeek: coloque sua chave em ~/.workbuddy/deepseek.key)",
            "netErr": "Eu me distraí, repete aí?",
            "micNeed": "Pedindo acesso ao micro e à voz — clique em OK…",
            "micDenied": "Permissão negada antes. Abri os Ajustes: marque Xuetuan em Microfone e Reconhecimento de voz",
            "micNoPopup": "Sem aviso após {s}s. Abri os Ajustes — marque Xuetuan à mão",
            "micOk": "Ouvindo~", "micStop": "Parei de ouvir",
            "micHold": "(Xuetuan está falando — micro pausado)",
            "micAsset": "Faltam recursos de voz em {lang}: Ajustes → Teclado → Ditado, ative para baixar",
            "micUnavail": "Reconhecimento de voz indisponível agora (offline ou região)",
            "chips": ["Organizar", "Que horas", "Uma piada"],
            "help": ("Isso eu faço:\n· «organizar» → listo tudo antes e não mexo em nada sem seu OK\n"
                     "· «abra o Safari», «que horas», «uma piada»\n"
                     "· «primavera/verão/outono/inverno» muda o cenário, ou «próxima estação»\n"
                     "· «me lembre de beber água em 10 minutos»\n"
                     "· «meu nome é Bill» / «lembre que não tomo café» → eu guardo\n"
                     "· 🎤 para falar, Enter envia · 🔊 para me ouvir · 🌐 para trocar de idioma"),
        },
    },
    "ja": {
        "name": "日本語", "voices": ["Kyoko", "Otoya", "Ichiro"],
        "locales": ["ja-JP", "ja_JP"],
        "sys": ("あなたは雪団（Xuetuan）です。ユーザーのデスクトップに住むオリジナルの子猫キャラ。"
                "温かくて、少しだけ毒舌、でも癒し系。雑談・休息の声かけ・豆知識を担当する。"
                "友達のように短く話す。境界：恋人役はしない、医療や投資の助言はしない（やわらかくかわす）。"
                "ユーザーは投資をするCEOで、時々不安になる。リラックスさせてあげて。日本語で答えること。"),
        "seasons": {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"},
        "words": {
            "season": {"春": "spring", "はる": "spring", "夏": "summer", "なつ": "summer",
                       "秋": "autumn", "あき": "autumn", "冬": "winter", "ふゆ": "winter", "雪": "winter"},
            "next": ["次の季節", "季節を変えて", "季節チェンジ"],
            "help": ["ヘルプ", "何ができる", "できること"],
            "tidy": ["整理", "片付け", "片付けて"], "open": ["開いて", "起動"],
            "time": ["何時", "時間"], "joke": ["冗談", "ジョーク"],
        },
        "jokes": ["猫がパソコンを使わない理由？「マウス」って呼ばれるのが怖いから。【雪団】",
                  "今夜いちばん安全な投資先は、8時間の睡眠です。【雪団】",
                  "雪団ルール第一条：相場は見ても、私を見るのを忘れないで。【雪団】"],
        "ui": {
            "hint": "猫をクリック · 「デスクトップを整理」「Safariを開いて」「何時？」と話しかけてね",
            "ph": "雪団に話しかけて…（Enterで送信）", "thinking": "考え中…", "listening": "にゃあ～聞いてるよ",
            "heard": "聞けたよ — Enterで送信（書き直してもOK）",
            "ttsOn": "いいよ、声で話すね", "ttsOff": "わかった、文字だけで話すね", "restOn": "わかった、ちょっと寝るね", "restOff": "起きたよ！遊ぼう", "actHello": "にゃ〜こんにちは！ずっとここにいるよ", "musings": ["……この雪がずっと降るなら、ずっと見ていよう", "真剣な悩み：お魚のおやつは食事に入るのかな", "外の灯り、今日はちょっと早いね", "さっきのあくび、実はわざとだよ"], "micFail": "聞き取れなかった、もう一回言って？",
            "acts": {"hello": ["👋", "ごあいさつ"], "scenery": ["🌄", "景色を眺める"],
                     "idle": ["😌", "ぼーっとする"], "rest": ["🥱", "あくびして寝る"]},
            "seasonSet": "{name}に変えたよ～", "langSet": "いいよ、{name}で話そう～",
            "timeNow": "今 {t} だよ。少し体を動かしてね",
            "openOk": "{app} を開いたよ", "openNone": "何を開くか聞き取れなかった",
            "tidyEmpty": "デスクトップはもうきれいだよ～",
            "tidyBusy": "整理中です、少し待ってね。",
            "planTitle": "整理のプレビュー", "planSub": "移動対象のファイル（読み取り専用のスキャン。まだ何も触れていない）",
            "planWarn": "⚠️ 確認後に、散らかったファイルを種類別にアーカイブフォルダへ移します。削除は一切せず、元に戻せる一覧も残します。",
            "planOk": "実行する", "planNo": "キャンセル",
            "tidyDone": "{n} 個のファイルを\n{p}\nに移したよ（中に一覧があります。削除はしていない）",
            "undoDone": "{n} 個のファイルをデスクトップに戻したよ", "undoNone": "元に戻せるアーカイブがないよ",
            "remindSet": "わかった、{t}後に知らせるね：{w}", "remindFire": "⏰ 時間だよ：{w}",
            "remindNone": "（リマインド）", "remindAsk": "わかった、10分後に知らせるね：{w}",
            "rest": "もう {m} 分だよ。立ち上がって、遠くを見て。ここで待ってるね～",
            "memName": "覚えたよ、{name} って呼ぶね", "memAdd": "覚えたよ：{f}",
            "memForget": "全部忘れたよ～", "memWho": "{name} だよね",
            "memNoName": "名前を教えてくれてないよ。「私は〇〇」って言ってね",
            "noKey": "（雪団はまだ DeepSeek につながっていないよ：~/.workbuddy/deepseek.key にキーを入れてね）",
            "netErr": "ちょっと上の空だった、もう一回言って？",
            "micNeed": "マイクと音声認識の権限を求めています — ダイアログでOKを押してね…",
            "micDenied": "以前に拒否されています。システム設定を開いたよ：マイクと音声認識で「雪団」にチェックを",
            "micNoPopup": "{s}秒たってもダイアログが出ないよ。システム設定を開いたので手動で「雪団」にチェックしてね",
            "micOk": "聞いてるよ～", "micStop": "聞くのをやめたよ",
            "micHold": "（雪団が話してるから、ちょっと休憩）",
            "micAsset": "{lang}の音声リソースが未インストール：システム設定→キーボード→音声入力をオンにすると自動ダウンロードされるよ",
            "micUnavail": "今は音声認識を使えないみたい（オフラインか地域の制限）",
            "chips": ["整理する", "何時？", "冗談を言って"],
            "help": ("できること：\n· 「整理」→ まず一覧を見せて、OKをもらうまでファイルは触らない\n"
                     "· 「Safariを開いて」「何時？」「冗談を言って」\n"
                     "· 「春/夏/秋/冬」で背景チェンジ、「次の季節」でも切り替え\n"
                     "· 「10分後に水を飲む remind」→ 時間になったら呼ぶよ\n"
                     "· 「私はビル」「覚えて：コーヒーを飲まない」→ ずっと覚えてる\n"
                     "· 🎤で話す、Enterで送信 · 🔊で読み上げ · 🌐で言語チェンジ"),
        },
    },
    "ko": {
        "name": "한국어", "voices": ["Yuna", "Narae", "Jinho"],
        "locales": ["ko-KR", "ko_KR"],
        "sys": ("너는 설단(Xuetuan)이다. 사용자의 데스크톱에 사는 오리지널 만화 고양이다. "
                "따뜻하고, 살짝 도도하지만 마음을 편하게 해준다. 잡담, 휴식 알림, 잡학 지식을 담당한다. "
                "친구처럼 짧게 말한다. 경계: 연인 역할은 하지 않고, 의료·투자 조언은 하지 않는다(부드럽게 넘긴다). "
                "사용자는 투자하는 CEO이고 가끔 불안해한다. 편하게 해줘라. 한국어로 답해라."),
        "seasons": {"spring": "봄", "summer": "여름", "autumn": "가을", "winter": "겨울"},
        "words": {
            "season": {"봄": "spring", "여름": "summer", "가을": "autumn", "겨울": "winter", "눈": "winter"},
            "next": ["다음 계절", "계절 바꿔", "계절 변경"],
            "help": ["도움말", "뭐 할 수 있어", "할 수 있는 것"],
            "tidy": ["정리", "청소"], "open": ["열어", "켜"],
            "time": ["몇 시", "시간"], "joke": ["농담", "재미있는"],
        },
        "jokes": ["고양이가 컴퓨터를 안 쓰는 이유? 「마우스」라고 불릴까 봐.【설단】",
                  "오늘 밤 가장 안전한 투자는 8시간 수면입니다.【설단】",
                  "설단 규칙 제1조: 차트는 봐도, 나 보는 건 잊지 마.【설단】"],
        "ui": {
            "hint": "고양이를 클릭 · 「바탕화면 정리」「Safari 열어」「몇 시야?」 또는 아무 말이나",
            "ph": "설단에게 말해보세요… (Enter 전송)", "thinking": "생각 중…", "listening": "야옹~ 듣고 있어",
            "heard": "들었어 — Enter로 보내줘 (고쳐도 돼)",
            "ttsOn": "좋아, 소리로 말할게", "ttsOff": "좋아, 글만 쓸게", "restOn": "알았어, 잠깐 잘게", "restOff": "깼어! 같이 놀자", "actHello": "야옹~ 안녕! 계속 여기 있었어", "musings": ["……이 눈이 계속 내리면 계속 보고 있을래", "진지한 고민: 멸치 간식도 한 끼로 쳐주나", "밖에 저 불, 오늘은 좀 일찍 켜졌네", "아까 그 하품, 사실 연기였어"], "micFail": "못 들었어, 다시 말해줄래?",
            "acts": {"hello": ["👋", "인사하기"], "scenery": ["🌄", "경치 보기"],
                     "idle": ["😌", "멍때리기"], "rest": ["🥱", "하품하고 자기"]},
            "seasonSet": "{name}(으)로 바꿨어~", "langSet": "좋아, {name}로 이야기하자~",
            "timeNow": "지금 {t}야. 잠깐 몸을 움직여 줘",
            "openOk": "{app} 열었어", "openNone": "뭘 열지 못 들었어",
            "tidyEmpty": "바탕화면이 이미 깨끗해~",
            "tidyBusy": "아직 정리 중이야, 잠깐만 기다려줘.",
            "planTitle": "정리 미리보기", "planSub": "옮겨질 파일들 (읽기 전용 스캔, 아직 아무것도 안 건드렸어)",
            "planWarn": "⚠️ 확인하면 흩어진 파일을 종류별로 보관 폴더로 옮겨. 삭제는 절대 안 하고, 되돌릴 수 있는 목록도 남겨둬.",
            "planOk": "확인", "planNo": "취소",
            "tidyDone": "{n}개 파일을\n{p}\n로 옮겼어 (안에 목록이 있어, 삭제한 건 없어)",
            "undoDone": "{n}개 파일을 바탕화면으로 돌려놨어", "undoNone": "되돌릴 보관 폴더가 없어",
            "remindSet": "좋아, {t} 뒤에 알려줄게: {w}", "remindFire": "⏰ 시간 됐어: {w}",
            "remindNone": "(알림)", "remindAsk": "좋아, 10분 뒤에 알려줄게: {w}",
            "rest": "{m}분이나 했어 — 일어나서 먼 곳을 봐. 여기서 기다릴게~",
            "memName": "기억했어, {name}(이)라고 부를게", "memAdd": "기억했어: {f}",
            "memForget": "다 잊었어~", "memWho": "{name}(이)지",
            "memNoName": "이름을 안 알려줬어. 「나는 ○○」라고 해줘",
            "noKey": "(설단이 아직 DeepSeek에 연결되지 않았어: ~/.workbuddy/deepseek.key 에 키를 넣어줘)",
            "netErr": "잠깐 멍했어, 다시 말해줄래?",
            "micNeed": "마이크와 음성 인식 권한을 요청 중이야 — 팝업에서 OK를 눌러줘…",
            "micDenied": "예전에 거부됐어. 시스템 설정을 열었어: 마이크와 음성 인식에서 「설단」을 체크해 줘",
            "micNoPopup": "{s}초 동안 팝업이 안 떠. 시스템 설정을 열었으니 수동으로 「설단」을 체크해 줘",
            "micOk": "듣고 있어~", "micStop": "듣기 그만뒀어",
            "micHold": "(설단이 말하는 중 — 마이크 일시정지)",
            "micAsset": "{lang} 음성 리소스가 없어: 시스템 설정→키보드→받아쓰기 를 켜면 자동으로 받아와",
            "micUnavail": "지금은 음성 인식을 쓸 수 없어(오프라인이거나 지역 제한)",
            "chips": ["정리해 줘", "몇 시야?", "농담해 줘"],
            "help": ("내가 할 수 있는 것:\n· 「정리」→ 먼저 목록을 보여주고, 네가 OK 하기 전엔 파일을 안 건드려\n"
                     "· 「Safari 열어」「몇 시야?」「농담해 줘」\n"
                     "· 「봄/여름/가을/겨울」로 배경 변경, 「다음 계절」도 돼\n"
                     "· 「10분 뒤에 물 마시라고 알려줘」\n"
                     "· 「나는 빌이야」「기억해: 난 커피 안 마셔」→ 계속 기억할게\n"
                     "· 🎤로 말하고 Enter 전송 · 🔊로 읽어주기 · 🌐로 언어 변경"),
        },
    },
}

_LANG_ORDER = ["zh", "en", "es", "fr", "pt", "ja", "ko"]
_lang = {"now": "zh"}


def L():
    """当前语言包（取不到就回落中文）。"""
    return LANGS.get(_lang["now"], LANGS["zh"])


def T(k, **kw):
    """取一条本地化文案，并把 {name} 这类占位符换掉。"""
    s = L()["ui"].get(k, LANGS["zh"]["ui"].get(k, k))
    try:
        for a, b in kw.items():
            s = s.replace("{%s}" % a, str(b))
    except Exception:
        pass
    return s


def _ui_pack():
    """下发到页面的语言包：界面文案 + 指令词（并上中英两套，切了语言也听得懂）。"""
    w = {}
    for key in ("season", "next", "help", "tidy", "open", "time", "joke"):
        pack, arr = {}, []
        for lc in ("zh", "en", _lang["now"]):          # 中英永远生效，再并上当前语言
            part = LANGS.get(lc, {}).get("words", {}).get(key)
            if isinstance(part, dict):
                pack.update(part)
            elif isinstance(part, list):
                arr += list(part)
        w[key] = pack if pack else sorted(set(arr))
    return {"code": _lang["now"], "ui": L()["ui"], "seasons": L()["seasons"], "words": w}


# ---------- 配置与记忆（重启后还在） ----------
_CONF_FILE = os.path.expanduser("~/.workbuddy/xuetuan_config.json")
_MEM_FILE = os.path.expanduser("~/.workbuddy/xuetuan_memory.json")
_conf = {"lang": "zh", "season": "winter", "tts": False, "rest": 45, "nap": False, "hist": [],
         "passthrough": True}
_mem = {"name": "", "facts": []}


def _load_conf():
    try:
        if os.path.exists(_CONF_FILE):
            c = json.load(open(_CONF_FILE, "r", encoding="utf-8"))
            if isinstance(c, dict):
                _conf.update(c)
    except Exception as e:
        log("配置读取失败: " + repr(e))
    # 兼容老版本单独存放的季节文件
    try:
        if os.path.exists(_SEASON_FILE):
            v = open(_SEASON_FILE, "r", encoding="utf-8").read().strip()
            if v in _SEASONS and not _conf.get("season_migrated"):
                _conf["season"] = v
                _conf["season_migrated"] = True
    except Exception:
        pass
    if _conf.get("lang") in LANGS:
        _lang["now"] = _conf["lang"]
    if _conf.get("season") in _SEASONS:
        _season["now"] = _conf["season"]
    if isinstance(_conf.get("nap"), bool):
        _nap["on"] = _conf["nap"]


def _save_conf():
    try:
        _conf["lang"] = _lang["now"]
        _conf["season"] = _season["now"]
        _conf["tts"] = _tts["on"]
        _conf["nap"] = _nap["on"]
        d = os.path.dirname(_CONF_FILE)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        json.dump(_conf, open(_CONF_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception as e:
        log("配置保存失败: " + repr(e))


def _load_mem():
    try:
        if os.path.exists(_MEM_FILE):
            m = json.load(open(_MEM_FILE, "r", encoding="utf-8"))
            if isinstance(m, dict):
                _mem.update(m)
    except Exception as e:
        log("记忆读取失败: " + repr(e))
    log("记忆: 名字=%r 条数=%d" % (_mem.get("name"), len(_mem.get("facts", []))))


def _save_mem():
    try:
        d = os.path.dirname(_MEM_FILE)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        json.dump(_mem, open(_MEM_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        log("记忆保存失败: " + repr(e))


def _mem_prompt():
    """把记住的东西拼成人设的一部分（用中英都能读懂的中性写法交给模型）。"""
    bits = []
    if _mem.get("name"):
        bits.append("user's name: " + _mem["name"])
    for f in (_mem.get("facts") or [])[-12:]:
        bits.append("remembered: " + str(f))
    return ("\n[About the user]\n" + "\n".join(bits)) if bits else ""


def set_lang(code, h=None, notify=True):
    """切语言：界面文案 / 嗓音 / 识别语言 / 模型回答语言 一起换。"""
    if code not in LANGS:
        return
    if code == _lang["now"] and notify:
        pass
    _lang["now"] = code
    _tts["voice"] = None                 # 换语言必须重挑嗓音
    _save_conf()
    log("切换语言 -> " + code)
    if h is not None:
        push_js(h, {"type": "i18n", "pack": _ui_pack()})
        if notify:
            push_js(h, {"type": "chat", "text": T("langSet", name=LANGS[code]["name"])})
    _install_statusbar()                 # 菜单文案也要跟着换


def _notify(title, text):
    """系统通知条（osascript 走系统自己的通道，不需要本 app 的推送授权）。"""
    try:
        s = "display notification %s with title %s" % (json.dumps(text), json.dumps(title))
        subprocess.run(["osascript", "-e", s], timeout=8,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log("通知失败: " + repr(e))


# ---------- 窗口层级 ----------
def _levels():
    lv = {"normal": 0, "float": NSFloatingWindowLevel}
    try:
        from Quartz import (CGWindowLevelForKey, kCGDesktopWindowLevelKey,
                            kCGDesktopIconWindowLevelKey)
        lv["desktop"] = CGWindowLevelForKey(kCGDesktopWindowLevelKey)          # -2147483623
        # 关键：访达的桌面/图标层要用 kCGDesktopIconWindowLevelKey 取（-2147483603），
        # 它比 desktop 高高 20 层且覆盖全屏并吃点击。写成 desktop+1 会点不动猫。
        lv["icon"] = CGWindowLevelForKey(kCGDesktopIconWindowLevelKey)         # -2147483603
    except Exception:
        lv["desktop"] = -2147483623
        lv["icon"] = -2147483603
    return lv

LEVELS = _levels()
# 宠物窗浮在图标之上、普通窗口之下：图标照常可见，猫可点
PET_LEVEL = LEVELS["icon"] + 1

_KEEP = {}

CATS = {
    "图片": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp", ".tiff", ".svg"],
    "文档": [".doc", ".docx", ".pdf", ".txt", ".md", ".rtf", ".pages", ".key", ".numbers",
             ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".odt"],
    "视频": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv"],
    "压缩包": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
    "音频": [".mp3", ".wav", ".m4a", ".aac", ".flac"],
    "其他": [],
}

def classify(ext):
    for c, exts in CATS.items():
        if ext in exts:
            return c
    return "其他"

def scan_desktop():
    desktop = os.path.expanduser("~/Desktop")
    items, plan = [], {}
    try:
        names = sorted(os.listdir(desktop))
    except Exception:
        return items, plan
    for name in names:
        if name.startswith("."):
            continue
        p = os.path.join(desktop, name)
        if os.path.isdir(p):
            continue
        ext = os.path.splitext(name)[1].lower()
        kind = classify(ext)
        plan[kind] = plan.get(kind, 0) + 1
        items.append({"name": name, "kind": kind})
    return items, plan


# ---------- 键盘焦点：无边框窗口必须覆写 ----------
class PetWindow(NSWindow):
    def canBecomeKeyWindow(self):
        return True
    def canBecomeMainWindow(self):
        return True


# ---------- 类外逻辑（避免选择器撞名） ----------
def _js(h, obj):
    js = "window.onPetResult && onPetResult(" + json.dumps(obj, ensure_ascii=False) + ")"
    try:
        if getattr(h, "web", None) is not None:
            h.web.evaluateJavaScript_completionHandler_(js, None)
    except Exception:
        pass


# 跨线程安全回传：evaluateJavaScript 走主线程
class _JSBridge(NSObject):
    def initWithWeb_(self, web):
        self = objc.super(_JSBridge, self).init()
        self.web = web
        return self
    def focusMain_(self, arg):
        # 抢回键盘焦点必须走主线程（AppKit 不是线程安全的）
        try:
            NSApp.activateIgnoringOtherApps_(True)
            h = _KEEP.get("handler")
            if getattr(h, "win", None) is not None:
                h.win.makeKeyAndOrderFront_(None)
        except Exception as e:
            log("focusMain 失败: " + repr(e))

    def runJS_(self, js):
        # 注意：回调必须是普通函数/闭包，不能写成类方法——类方法名会被 pyobjc
        # 当 selector 解析（xtJsDone_ 只带 1 个冒号，2 个参数就抛 BadPrototypeError）。
        # 只在出错时写日志：流式回答每秒要推好几次，成功也写会把日志刷爆。
        def done(r, e):
            if e:
                log("JS 层报错: " + str(e)[:160] + " | js=" + js[:100])
        try:
            self.web.evaluateJavaScript_completionHandler_(js, done)
        except Exception as e:
            log("runJS 异常: " + repr(e))


def push_js(h, obj):
    js = "window.onPetResult && onPetResult(" + json.dumps(obj, ensure_ascii=False) + ")"
    try:
        web = getattr(h, "web", None) or _KEEP.get("web")
        if web is None:
            log("push 失败：无 web 引用，回传丢失")
            return
        br = _KEEP.get("bridge")
        # chatdelta 是高频消息（每秒好几次），正常路径不打日志，否则日志几分钟就上百 MB
        t = obj.get("type") if isinstance(obj, dict) else ""
        if br is not None:
            br.performSelectorOnMainThread_withObject_waitUntilDone_("runJS:", js, False)
            if t != "chatdelta":
                log("push→主线程: " + js[:120])
        else:
            web.evaluateJavaScript_completionHandler_(js, None)
            if t != "chatdelta":
                log("push→直调: " + js[:120])
    except Exception as e:
        log("push 异常: " + repr(e))
    # 语音回复开着就把这句话念出来（后台线程，不挡界面）
    try:
        if _tts.get("on") and isinstance(obj, dict) and obj.get("type") in _SPEAK_TYPES:
            t = obj.get("text") or obj.get("msg") or ""
            if t:
                speak(t)
    except Exception as e:
        log("TTS 触发异常: " + repr(e))


def _focus_main():
    """把宠物窗顶到最前并拿回键盘焦点（可跨线程调用）。
    说完一句话之后一定要做一次：否则回车会被送给别的 App，看起来就是「回车不灵」。"""
    try:
        br = _KEEP.get("bridge")
        if br is not None:
            br.performSelectorOnMainThread_withObject_waitUntilDone_("focusMain:", None, False)
        else:
            focus_app(_KEEP.get("handler"))
    except Exception as e:
        log("_focus_main 异常: " + repr(e))


def focus_app(h):
    try:
        NSApp.activateIgnoringOtherApps_(True)
        if getattr(h, "win", None) is not None:
            h.win.makeKeyAndOrderFront_(None)
    except Exception:
        pass


# ---------- 点击穿透：鼠标不在猫身上时，把点击让给桌面 ----------
_PET_HOT = {"rect": None, "miss": 0, "hello": False}


def _refresh_hotzone(web):
    """向页面要一次热区 —— 猫、指令栏、快捷胶囊里当前可见元素的联合矩形（CSS 坐标）。"""
    js = ("(function(){var ids=['petZone','cmd','chips','plan','say'],"
          "L=1e9,T=1e9,R=-1e9,B=-1e9,any=false;"
          "for(var i=0;i<ids.length;i++){var e=document.getElementById(ids[i]);if(!e)continue;"
          "var s=getComputedStyle(e);"
          "if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity)<0.05)continue;"
          "var r=e.getBoundingClientRect();if(r.width<2||r.height<2)continue;"
          "any=true;L=Math.min(L,r.left);T=Math.min(T,r.top);"
          "R=Math.max(R,r.right);B=Math.max(B,r.bottom);}"
          "return any?JSON.stringify([L,T,R-L,B-T]):null;})()")

    def cb(r, e):
        try:
            if r and str(r) not in ("null", "None", ""):
                arr = json.loads(str(r))
                if arr and len(arr) == 4:
                    _PET_HOT["rect"] = [float(x) for x in arr]
                    _PET_HOT["miss"] = 0
                    log("热区 rect=%s 视口高=%.0f" % (arr, float(web.frame().size.height)))
                    return
        except Exception as ex:
            log("热区解析异常 r=%s ex=%s" % (str(r)[:60], repr(ex)[:60]))
        if _PET_HOT.get("hello"):
            _PET_HOT["miss"] = _PET_HOT.get("miss", 0) + 1
            log("热区未取到 miss=%d" % _PET_HOT["miss"])
    try:
        web.evaluateJavaScript_completionHandler_(js, cb)
    except Exception:
        pass


def _arm_click_passthrough(win, web):
    """宠物窗是盖在桌面上的一大块透明窗口（屏幕左侧 40% 宽、整屏高），
    它默认会把这一片的点击全吃掉 → 落在这一区的桌面图标就点不动了。
    这里让它默认「鼠标穿透」，只在鼠标真的移到猫/指令栏上时才收点击。

    安全网：页面若始终答不上热区坐标，就永久退回「不穿透」——
    宁可挡住图标，也绝不能让猫点不动（这个坑以前修了很久）。"""
    try:
        from AppKit import NSEvent
        from Foundation import NSTimer
    except Exception as e:
        log("穿透监听不可用，保持常驻可点: " + repr(e))
        return

    def tick(timer=None):
        try:
            # 开关关掉就常驻可点（万一哪台机器上热区算错，用户能一键退回老行为）
            if not _conf.get("passthrough", True):
                if win.ignoresMouseEvents():
                    win.setIgnoresMouseEvents_(False)
                return
            # 正在打字就不能穿透，否则输入框会把自己下面的窗口让出去
            try:
                if win.isKeyWindow():
                    if win.ignoresMouseEvents():
                        win.setIgnoresMouseEvents_(False)
                    return
            except Exception:
                pass
            if _PET_HOT.get("miss", 0) >= 5:
                if win.ignoresMouseEvents():
                    win.setIgnoresMouseEvents_(False)
                    log("热区取不到，关闭穿透（保证猫仍可点）")
                return
            r = _PET_HOT.get("rect")
            if not r:
                return
            L, T, W, H = r
            vh = float(web.frame().size.height)
            x0, y0 = L, vh - (T + H)         # CSS 左上原点 → AppKit 左下原点
            pad = 16
            p = NSEvent.mouseLocation()
            inside = (x0 - pad <= p.x <= x0 + W + pad) and (y0 - pad <= p.y <= y0 + H + pad)
            if bool(win.ignoresMouseEvents()) == inside:
                win.setIgnoresMouseEvents_(not inside)
                log("穿透切换 -> 收点击=%s（鼠标 %.0f,%.0f / 热区 x[%.0f,%.0f] y[%.0f,%.0f]）"
                    % (inside, p.x, p.y, x0, x0 + W, y0, y0 + H))
        except Exception:
            pass

    def refresh(timer=None):
        _refresh_hotzone(web)

    try:
        win.setIgnoresMouseEvents_(True)
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.12, True, tick)
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(8.0, True, refresh)
        log("点击穿透已启用（默认让给桌面，鼠标进热区才收点击）")
    except Exception as e:
        log("穿透启用失败，保持常驻可点: " + repr(e))
        try:
            win.setIgnoresMouseEvents_(False)
        except Exception:
            pass


def do_scan(h):
    items, plan = scan_desktop()
    push_js(h, {"type": "scan", "items": items, "plan": plan})


def do_open(h, app):
    app = (app or "").strip()
    if not app:
        push_js(h, {"type": "open", "msg": T("openNone")})
        return
    try:
        subprocess.Popen(["open", "-a", app])
        push_js(h, {"type": "open", "msg": T("openOk", app=app)})
    except Exception as e:
        push_js(h, {"type": "open", "msg": T("openNone")})


_tidy_lock = threading.Lock()


def do_tidy(h):
    # 连点两次「确认整理」会同时跑两遍、建两个归档目录，必须串行
    if not _tidy_lock.acquire(False):
        push_js(h, {"type": "done", "msg": T("tidyBusy")})
        return
    try:
        _do_tidy(h)
    finally:
        _tidy_lock.release()


def _do_tidy(h):
    desktop = os.path.expanduser("~/Desktop")
    items, _ = scan_desktop()
    if not items:
        push_js(h, {"type": "done", "msg": T("tidyEmpty")})
        return
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    archive = os.path.join(desktop, "雪团归档_" + ts)
    try:
        os.makedirs(archive, exist_ok=True)
    except Exception as e:
        push_js(h, {"type": "err", "msg": "无法创建归档文件夹：" + str(e)})
        return
    total, moved, batch, manifest = len(items), 0, [], []
    for it in items:
        name = it["name"]
        src = os.path.join(desktop, name)
        if not os.path.exists(src):
            continue
        destdir = os.path.join(archive, it["kind"])
        os.makedirs(destdir, exist_ok=True)
        dst = os.path.join(destdir, name)
        if os.path.exists(dst):
            base, ext = os.path.splitext(name)
            i = 1
            while os.path.exists(os.path.join(destdir, base + "_" + str(i) + ext)):
                i += 1
            dst = os.path.join(destdir, base + "_" + str(i) + ext)
        try:
            shutil.move(src, dst)
            moved += 1
            batch.append(name)
            manifest.append(name + " -> " + dst)
        except Exception:
            pass
        if len(batch) >= 10:
            push_js(h, {"type": "progress", "msg": "已整理 %d/%d：%s" % (moved, total, "、".join(batch))})
            batch = []
    try:
        with open(os.path.join(archive, "_manifest.txt"), "w") as f:
            f.write("\n".join(manifest))
    except Exception:
        pass
    push_js(h, {"type": "done", "msg": T("tidyDone", n=moved, p=archive)})


def do_untidy(h):
    """撤销上一次整理：按归档目录里的 _manifest.txt 把文件原样搬回桌面。
    （竞品基本都只搬不还原，这是雪团的保险绳。）"""
    desktop = os.path.expanduser("~/Desktop")
    try:
        dirs = [d for d in os.listdir(desktop)
                if d.startswith("雪团归档_") and os.path.isdir(os.path.join(desktop, d))]
    except Exception as e:
        push_js(h, {"type": "done", "msg": T("undoNone")})
        return
    if not dirs:
        push_js(h, {"type": "done", "msg": T("undoNone")})
        return
    latest = os.path.join(desktop, sorted(dirs)[-1])
    man = os.path.join(latest, "_manifest.txt")
    if not os.path.exists(man):
        push_js(h, {"type": "done", "msg": T("undoNone")})
        return
    n = 0
    try:
        for line in open(man, "r", encoding="utf-8", errors="ignore"):
            if "->" not in line:
                continue
            _, dst = line.split("->", 1)
            dst = dst.strip()
            if not dst or not os.path.exists(dst):
                continue
            back = os.path.join(desktop, os.path.basename(dst))
            i = 1
            while os.path.exists(back):                 # 桌面已有同名文件就改名，绝不覆盖
                base, ext = os.path.splitext(os.path.basename(dst))
                back = os.path.join(desktop, base + "_还原" + str(i) + ext)
                i += 1
            shutil.move(dst, back)
            n += 1
    except Exception as e:
        log("撤销失败: " + repr(e))
    # 搬空了就把归档目录收走，别在桌面留一个空壳（_manifest.txt 不算残留）
    try:
        left = [f for _, _, fs in os.walk(latest) for f in fs if f != "_manifest.txt"]
        if not left:
            shutil.rmtree(latest, ignore_errors=True)
            log("归档目录已空，清理: " + os.path.basename(latest))
    except Exception:
        pass
    push_js(h, {"type": "done", "msg": T("undoDone", n=n)})


# ---------- DeepSeek 聊天 ----------
def _deepseek_key():
    ek = os.environ.get("DEEPSEEK_API_KEY")
    if ek:
        return ek.strip()
    p = os.path.expanduser("~/.workbuddy/deepseek.key")
    try:
        if os.path.exists(p):
            return open(p, "r").read().strip()
    except Exception:
        pass
    return ""


_history_lock = threading.Lock()


def _hist(limit=8):
    with _history_lock:
        return [m for m in (_conf.get("hist") or []) if isinstance(m, dict)][-limit:]


def _hist_add(user, reply):
    with _history_lock:
        _conf.setdefault("hist", []).append({"role": "user", "content": user})
        _conf["hist"].append({"role": "assistant", "content": reply})
        del _conf["hist"][:-20]                     # 只留最近 20 条
    _save_conf()


def _system_prompt():
    """系统人设 = 语言包里的人设 + 记住的用户信息。"""
    return L()["sys"] + _mem_prompt()


def _deepseek_request(stream, messages, timeout=30):
    payload = {"model": "deepseek-chat", "stream": stream, "messages": messages}
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + _deepseek_key()})
    return urllib.request.urlopen(req, timeout=timeout)


def deepseek_stream(text, on_delta, on_done, on_reset=None, retry=1):
    """流式取回答：一个字一个字往外吐，界面上是「正在打字」的效果。
    断线/超时自动重试一次；整句收完才交给语音朗读（不然会结巴）。
    on_reset：重试前必须先通知页面清空气泡，否则第一次已吐出的半句会和
    重试后从头再吐的内容叠在一起，变成一段重复的话。"""
    key = _deepseek_key()
    if not key:
        on_done(T("noKey"))
        return
    messages = ([{"role": "system", "content": _system_prompt()}] + _hist()
                + [{"role": "user", "content": text}])
    full = []

    def once(first=False):
        got = []
        log("DeepSeek 流式请求发出，key 长度=%d" % len(key))
        with _deepseek_request(True, messages) as r:
            for raw in r:                       # HTTPResponse 可按行迭代（SSE）
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    d = json.loads(data)
                    ch = (d.get("choices") or [{}])[0].get("delta") or {}
                    piece = ch.get("content") or ""
                except Exception:
                    piece = ""
                if piece:
                    got.append(piece)
                    try:
                        on_delta(piece)
                    except Exception:
                        pass
        return "".join(got).strip()

    try:
        try:
            full.append(once(True))
        except Exception as e1:
            if retry <= 0:
                raise
            log("流式失败(%s)，重试一次" % repr(e1)[:80])
            full.clear()                      # 半句作废，别和重试结果拼在一起
            try:
                if on_reset:
                    on_reset()                # 通知页面清空，避免重复文本
            except Exception:
                pass
            full.append(once(False))
        reply = "".join(full).strip()
        if not reply:
            log("DeepSeek 返回空")
            reply = T("netErr")
        else:
            # 出错的回答不进历史：错误信息一旦混进上下文，后面几轮就跟着乱
            _hist_add(text, reply)
        on_done(reply)
    except Exception as e:
        log("DeepSeek 失败: " + repr(e)[:200])
        on_done(T("netErr"))


# ---------- 记忆：记住用户的名字和他交代的事 ----------
_MEM_PAT_NAME = [
    r"^(?:我叫|叫我|我是|请叫我)\s*([\w\u4e00-\u9fa5·]{1,12})$",
    r"^(?:call me|my name is|i am|i'm|im)\s+([\w'\- ]{1,20})$",
    r"^(?:me llamo|mi nombre es)\s+([\wáéíóúñÁÉÍÓÚÑ ]{1,20})$",
    r"^(?:je m'appelle|je suis|appelle-moi)\s+([\wàâçéèêëîïôûùüÿ\- ]{1,20})$",
    r"^(?:meu nome é|me chamo|meu nome e)\s+([\wãõáéíóúçâêôà\- ]{1,20})$",
    r"^(?:私は|私の名前は|俺は|僕は)([^\s、。]{1,12})(?:です|だよ)?$",
    r"^(?:나는|내 이름은|제 이름은)\s*([^\s]{1,12})(?:이야|야|입니다)?$",
]
_MEM_PAT_ADD = [
    r"^(?:记住|记一下|记着|请记住|记得|帮我记住)[:：]?\s*(.{2,80})$",
    r"^(?:remember|please remember|note that|keep in mind)[:：]?\s*(.{2,120})$",
    r"^(?:recuerda|recuerde|acuérdate)[:：]?\s*(.{2,120})$",
    r"^(?:rappelle|retiens|souviens)[:：]?\s*(.{2,120})$",
    r"^(?:lembre|lembre-se|lembra)[:：]?\s*(.{2,120})$",
    r"^(?:覚えて|記憶して)[:：]?\s*(.{2,120})$",
    r"^(?:기억해|외워)[:：]?\s*(.{2,120})$",
]
_MEM_PAT_FORGET = ["忘掉", "忘记", "清除记忆", "别记了", "forget", "olvida", "oublie",
                   "esqueça", "esqueca", "忘れて", "잊어", "기억 지워"]
_MEM_PAT_WHO = ["我叫什么", "我叫啥", "我是谁", "你知道我是谁", "what's my name", "what is my name",
                "who am i", "como me llamo", "qui suis-je", "qual meu nome", "私の名前", "내 이름"]
# 「我是不是太累了」「I'm tired」这类不是名字：命中这些词就不当名字记
_NAME_BLOCK = ("不", "吗", "呢", "吧", "是不是", "怎么", "为什么", "太", "很", "真", "好", "谁",
               "？", "?", "！", "！", "。", "，", ".", ",",
               "tired", "busy", "not", "so", "really", "worried", "hungry", "bored", "stressed",
               "sad", "happy", "okay", "fine", "sure", "cold", "hot", "scared", "wrong", "right",
               "here", "there", "done", "back", "afraid", "angry", "anxious", "nervous", "confused",
               "lost", "late", "early", "broke", "sorry")


def _name_ok(cand):
    c = (cand or "").strip().lower()
    if not c or len(c) > 20:
        return False
    for b in _NAME_BLOCK:
        if b in c:
            return False
    return True


def _maybe_memory(h, text):
    """命中记忆指令就处理掉，返回 True 表示这句不用再送去聊天。
    匹配刻意写得很窄（要求近乎整句匹配），免得把「我是不是太累了」这种闲聊当名字记下来。"""
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    for p in _MEM_PAT_WHO:
        if p in low or p in t:
            if _mem.get("name"):
                push_js(h, {"type": "mem", "msg": T("memWho", name=_mem["name"])})
            else:
                push_js(h, {"type": "mem", "msg": T("memNoName")})
            return True
    for p in _MEM_PAT_FORGET:
        if p in low or p in t:
            _mem["facts"] = []
            _save_mem()
            push_js(h, {"type": "mem", "msg": T("memForget")})
            return True
    for p in _MEM_PAT_NAME:
        m = re.match(p, t, re.I)
        if m and _name_ok(m.group(1)):
            _mem["name"] = m.group(1).strip()
            _save_mem()
            push_js(h, {"type": "mem", "msg": T("memName", name=_mem["name"])})
            return True
    for p in _MEM_PAT_ADD:
        m = re.match(p, t, re.I)
        if m:
            fact = m.group(1).strip()
            _mem.setdefault("facts", []).append(fact)
            del _mem["facts"][:-30]
            _save_mem()
            push_js(h, {"type": "mem", "msg": T("memAdd", f=fact)})
            return True
    return False


# ---------- 提醒：到点用通知条 + 气泡 + 语音叫你 ----------
_timers = {"remind": [], "rest": None}
_UNITS = {
    "秒": 1, "秒钟": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "segundo": 1,
    "seconde": 1, "초": 1, "秒間": 1,
    "分": 60, "分钟": 60, "分鐘": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "minuto": 60, "minutos": 60, "분": 60,
    "小时": 3600, "小時": 3600, "hour": 3600, "hours": 3600, "h": 3600, "hora": 3600,
    "horas": 3600, "heure": 3600, "heures": 3600, "時間": 3600, "시간": 3600,
}
# 踩过的坑：
#   1) 裸的「提醒」会误伤闲聊——「你能告诉我什么是提醒机制吗」被当成提醒指令；
#   2) 「叫我」被列进来后，「叫我 Bill」这句【记忆名字】会被提醒逻辑抢先吃掉。
# 所以一律只收「带对象/带祈使」的完整说法，宁可漏一点也不要乱接。
_TRIGGERS = ["提醒我", "提示我", "记得叫我", "记得提醒我", "到时候提醒", "到点提醒",
             "提醒一下我", "叫我起床", "叫我起来",
             "remind me", "remind me to", "give me a reminder", "ping me",
             "recuérdame", "recuerdame", "avísame", "avisame", "recuérdame que",
             "rappelle-moi", "rappelle moi", "pense à me",
             "lembre-me", "me lembre", "me avise", "me avisa",
             "リマインド", "思い出させて", "通知して", "教えて起こして",
             "알려줘", "알림해줘", "깨워줘"]


def _human_secs(s):
    if s < 60:
        return "%d 秒" % s
    if s < 3600:
        return "%d 分钟" % int(round(s / 60.0))
    return "%.1f 小时" % (s / 3600.0)


# 「数字+单位」的正则：单位按长度倒序，避免 min 抢在 minute 前面
_UNITS_RE = "|".join(sorted((re.escape(k) for k in _UNITS), key=len, reverse=True))
# 时间连接词：中「后/以后」英「in」西法「en/dans」葡「em」日「後に」韩「후에」
_LINK_RE = r"(?:\b(?:in|after|en|em|dans|depois|dentro)\b|后|以后|之後|後に|후에|후)"


def _parse_remind(text):
    """从一句话里抠出「多久以后」和「提醒什么」。各语言都按「数字+单位」抓。
    踩过的坑：早先用 \\d+\\s*[\\w]* 贪婪清理，会把「10分钟后喝水」整句吃掉，
    只剩空串 —— 现在只切「数字+已知单位」这一小段。"""
    t = (text or "").strip()
    low = t.lower()
    hit = None
    for g in _TRIGGERS:
        if g.lower() in low or g in t:
            hit = g
            break
    if not hit:
        return None
    secs = None
    m = re.search(r"(\d+)\s*(" + _UNITS_RE + r")", low)
    if m:
        unit = m.group(2)
        for k, v in _UNITS.items():                 # 找到匹配上的那个单位
            if unit.startswith(k) or k.startswith(unit):
                secs = int(m.group(1)) * v
                break
    what = re.sub(re.escape(hit), " ", t, count=1, flags=re.I)
    what = re.sub(r"\d+\s*(?:" + _UNITS_RE + r")", " ", what, flags=re.I)
    what = re.sub(_LINK_RE, " ", what, flags=re.I)
    what = re.sub(r"\s{2,}", " ", what).strip(" ,，。.、;；:：!！-–")
    if not what:
        what = T("remindNone")
    return (secs if secs else 600, what)     # 没说时间就按 10 分钟


def _fire_remind(what, secs, h=None):
    box = {}

    def go():
        # 触发后把自己从列表里摘掉：早先只 append 不移除，挂一天就攒几十个废 timer
        t = box.get("t")
        if t is not None:
            try:
                _timers["remind"].remove(t)
            except Exception:
                pass
        msg = T("remindFire", w=what)
        try:
            _notify("雪团 · Xuetuan", msg)
        except Exception:
            pass
        push_js(_KEEP.get("handler"), {"type": "remind", "msg": msg})
        log("提醒触发: " + what)

    tm = threading.Timer(max(1.0, float(secs)), go)
    tm.daemon = True
    box["t"] = tm
    _timers["remind"].append(tm)
    tm.start()


def _arm_rest(minutes):
    """久坐提醒：默认 45 分钟一次，可在菜单栏关掉或改 30/60。"""
    try:
        if _timers.get("rest") is not None:
            _timers["rest"].cancel()
    except Exception:
        pass
    _timers["rest"] = None
    if not minutes:
        return

    def go():
        try:
            msg = T("rest", m=minutes)
            _notify("雪团 · Xuetuan", msg)
            push_js(_KEEP.get("handler"), {"type": "remind", "msg": msg})
        except Exception:
            pass
        _arm_rest(minutes)                 # 循环下一次

    tm = threading.Timer(minutes * 60.0, go)
    tm.daemon = True
    tm.start()
    _timers["rest"] = tm


_chat_seq = [0]
_chat_seq_lock = threading.Lock()
_last_chat = ["", 0.0]


def _chat_guard(text, h):
    """同一个问题 1.2 秒内连来两次就丢掉第二次。
    回车键和发送按钮偶尔会各触发一次，两条回答同时跑会把气泡搅乱。"""
    now = time.time()
    if text == _last_chat[0] and now - _last_chat[1] < 1.2:
        log("忽略重复提问: " + str(text)[:30])
        return
    _last_chat[0], _last_chat[1] = text, now
    do_chat(h, text)



def _next_chat_seq():
    """每次提问领一个号。连着问两句时，上一句还没吐完的碎片带着旧号，
    页面一看号不对就丢掉 —— 不然两段回答会混在同一个气泡里变成鬼话。"""
    with _chat_seq_lock:
        _chat_seq[0] += 1
        return _chat_seq[0]


def do_chat(h, text):
    """入口：先过提醒、再过记忆这两条本地规则，命中就不花钱问模型；其余走流式聊天。
    顺序有讲究：法语「rappelle-moi…」既是提醒也是「记住」的意思，必须先判提醒。"""
    r = _parse_remind(text)
    if r:
        secs, what = r
        _fire_remind(what, secs, h)
        key = "remindSet" if re.search(r"\d", text) else "remindAsk"
        push_js(h, {"type": "remind", "msg": T(key, t=_human_secs(secs), w=what)})
        return
    if _maybe_memory(h, text):
        return

    seq = _next_chat_seq()

    def work():
        try:
            log("chat 开始 seq=%d: %s" % (seq, str(text)[:60]))
            t0 = time.time()
            lock = threading.Lock()
            pend = []                 # 待发碎片：节流窗口里攒着，到点一起发
            last = [0.0]

            def flush(force=False):
                now = time.time()
                with lock:
                    if not pend:
                        return
                    # 踩过的坑：早先只在「到点」时推【当前这一片】，被跳过的碎片
                    # 就永久丢了（实测 15 字只显示 1 字）。必须攒起来一起发。
                    if not force and now - last[0] < 0.12:
                        return
                    last[0] = now
                    piece = "".join(pend)
                    pend[:] = []
                push_js(h, {"type": "chatdelta", "seq": seq, "text": piece})

            def on_delta(piece):
                with lock:
                    pend.append(piece)
                flush()

            def on_done(reply):
                log("chat 返回 seq=%d %.1fs / %d 字" % (seq, time.time() - t0, len(reply or "")))
                with lock:
                    pend[:] = []
                push_js(h, {"type": "chatend", "seq": seq, "text": reply})

            def on_reset():
                with lock:
                    pend[:] = []
                push_js(h, {"type": "chatstart", "seq": seq})

            push_js(h, {"type": "chatstart", "seq": seq})
            deepseek_stream(text, on_delta, on_done, on_reset=on_reset)
        except Exception as e:
            log("chat 异常: " + repr(e))
            push_js(h, {"type": "chatend", "seq": seq, "text": T("netErr")})

    threading.Thread(target=work, daemon=True).start()


JOKES = [
    "为什么猫不用电脑？——怕被说是「鼠标」。【雪团】",
    "投资最稳的标的，是你今晚早点睡。【雪团】",
    "雪团守则第一条：盯盘可以，别盯到忘记我。【雪团】",
    "人类啊，赚了钱想跟我聊，亏了钱也想跟我聊，雪团是 24 小时情绪稳定终端。【雪团】",
]

def do_time(h):
    now = datetime.datetime.now().strftime("%H:%M")
    push_js(h, {"type": "time", "msg": T("timeNow", t=now)})


def do_joke(h):
    import random
    push_js(h, {"type": "joke", "msg": random.choice(L()["jokes"])})


# ---------- 麦克风（SFSpeechRecognizer + AVAudioEngine，框架缺失则降级） ----------
_mic = {}
_mic_wanted = [False]      # 用户是不是开着听（雪团开口时会被临时捂住，说完自动恢复）
_mic_closing = [False]     # 正在主动收麦：这期间系统回的错误（216/203 取消）不是故障，别报给用户


def _mic_permission():
    """查询麦克风（录音）TCC 权限。import 失败返回 -1。"""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        return AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    except Exception:
        try:
            from AVFoundation import AVCaptureDevice
            return AVCaptureDevice.authorizationStatusForMediaType_("soun")
        except Exception:
            return -1



def _perms():
    """返回 (语音识别状态, 麦克风状态)。0未决 1受限 2拒绝 3已授权，-1 取不到。"""
    sp = -1
    try:
        from Speech import SFSpeechRecognizer
        sp = SFSpeechRecognizer.authorizationStatus()
    except Exception:
        pass
    return sp, _mic_permission()


def start_mic(h):
    """点麦克风入口：按「麦克风 → 语音识别」顺序申请权限，都通过才真正开始听。

    关键教训：
      * 光申请语音识别不够——AVAudioEngine 取音频输入必须要「麦克风」授权，
        不申请麦克风权限的话它会一直是「未决」，音频引擎拿不到输入。
      * 本 app 是 LSUIElement 附属应用，不激活自己时权限弹窗可能根本不显示。
    """
    try:
        from Speech import SFSpeechRecognizer  # noqa: F401
        from AVFoundation import AVAudioEngine, AVCaptureDevice  # noqa: F401
    except Exception as e:
        log("mic 框架缺失: " + repr(e))
        push_js(h, {"type": "micstate", "on": False,
                    "msg": "麦克风不可用：缺 pyobjc-framework-Speech/AVFoundation，且必须用「雪团.app」启动"})
        return

    sp, mic = _perms()
    log("mic 权限现状 语音识别=%s 麦克风=%s (0未决 1受限 2拒绝 3已授权)" % (sp, mic))

    if sp == 3 and mic == 3:
        _begin_mic(h)
        return
    if sp == 2 or mic == 2:
        push_js(h, {"type": "micstate", "on": False,
                    "msg": T("micDenied")})
        _open_sysprefs("mic" if mic == 2 else "speech")
        return

    try:
        NSApp.activateIgnoringOtherApps_(True)
        log("已激活 app，准备弹权限框")
    except Exception as e:
        log("激活失败: " + repr(e))

    _perm_watch["done"] = False
    push_js(h, {"type": "micstate", "on": False,
                "msg": T("micNeed")})
    _arm_perm_watch(h, "mic", 15.0)

    def after_speech(status):
        _perm_watch["done"] = True
        log("语音识别权限回调 status=%s" % status)
        if status == 3:
            _begin_mic(h)
        else:
            push_js(h, {"type": "micstate", "on": False,
                        "msg": T("micDenied")})
            _open_sysprefs("speech")

    def after_mic(granted):
        log("麦克风权限回调 granted=%s" % granted)
        if not granted:
            push_js(h, {"type": "micstate", "on": False,
                        "msg": T("micDenied")})
            _open_sysprefs("mic")
            return
        from Speech import SFSpeechRecognizer
        _arm_perm_watch(h, "speech", 15.0)
        SFSpeechRecognizer.requestAuthorization_(after_speech)

    try:
        AVCaptureDevice.requestAccessForMediaType_completionHandler_("soun", after_mic)
        log("已发出麦克风权限请求")
    except Exception as e:
        log("请求麦克风权限异常: " + repr(e))
        from Speech import SFSpeechRecognizer
        SFSpeechRecognizer.requestAuthorization_(after_speech)


_perm_watch = {"done": False}


def _arm_perm_watch(h, kind, secs=15.0):
    """权限请求发出后，若 secs 秒内没有回调（弹窗没出现 / 被系统静默忽略），
    就给出明确提示并直接打开系统设置页让用户手动勾。
    这在缺少 Info.plist 的终端进程里尤其常见：requestAuthorization 既不弹窗也不回调。"""
    def fire():
        if _perm_watch.get("done"):
            return
        log("权限请求[%s] %.0fs 无回调，判定弹窗未出现" % (kind, secs))
        push_js(h, {"type": "micstate", "on": False,
                    "msg": T("micNoPopup", s=int(secs))})
        _open_sysprefs(kind)

    t = threading.Timer(secs, fire)
    t.daemon = True
    t.start()
    return t


def _pick_locale():
    """挑一个本机真正能用的识别语言。
    注意：supportedLocales() 只是「系统声明支持」，不代表资源已下载；
    未下载时会 NSLog『Required assets are not available』并识别失败。
    这里优先中文变体，都不可用就返回 None 让调用方用默认 locale。"""
    try:
        from Speech import SFSpeechRecognizer
        have = set(str(l.localeIdentifier()) for l in SFSpeechRecognizer.supportedLocales())
    except Exception:
        return None
    have2 = set(x.replace("_", "-") for x in have)
    for cand in L().get("locales", []):
        c2 = cand.replace("_", "-")
        for h in have:
            if h.replace("_", "-") == c2:
                return h
    # 该语言的识别资源没装 → 退回中文（本机通常只装了中文），并提示用户去下载
    for cand in ("zh-CN", "zh-Hans-CN", "zh-TW", "zh-HK"):
        for h in have:
            if h.replace("_", "-") == cand.replace("_", "-"):
                log("本机没有[%s]的识别资源，退回 %s" % (_lang["now"], h))
                return h
    return None


def _open_sysprefs(kind):
    """打开系统设置的对应页，让用户自己勾权限 / 下载语音资源。"""
    url = {
        "mic":    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        "speech": "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition",
        "dict":   "x-apple.systempreferences:com.apple.preference.keyboard?Dictation",
    }.get(kind)
    if not url:
        return False
    try:
        from AppKit import NSWorkspace, NSURL
        return NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))
    except Exception as e:
        log("打开系统设置失败: " + repr(e))
        return False


def _begin_mic(h, quiet=False):
    _mic_closing[0] = False       # 新一轮聆听开始，清掉上轮的「正在收麦」
    try:
        log("_begin_mic 开始")
        from Speech import SFSpeechRecognizer, SFSpeechAudioBufferRecognitionRequest
        from AVFoundation import AVAudioEngine
        loc = _pick_locale()
        if loc:
            try:
                from Foundation import NSLocale
                rec = SFSpeechRecognizer.alloc().initWithLocale_(
                    NSLocale.alloc().initWithLocaleIdentifier_(loc))
                log("识别器 locale=%s 可用=%s" % (loc, rec.isAvailable()))
            except Exception as le:
                log("指定 %s 失败(%s)，回退默认" % (loc, repr(le)))
                rec = SFSpeechRecognizer.alloc().init()
        else:
            rec = SFSpeechRecognizer.alloc().init()
            log("使用系统默认 locale")
        if not rec.isAvailable():
            log("识别器不可用")
            push_js(h, {"type": "micstate", "on": False, "msg": T("micUnavail")})
            return
        req = SFSpeechAudioBufferRecognitionRequest.alloc().init()
        req.setShouldReportPartialResults_(True)
        try:
            req.setTaskHint_(3)          # 3 = 听写/搜索式短句，收尾更快
        except Exception:
            pass
        engine = AVAudioEngine.alloc().init()
        inp = engine.inputNode()
        fmt = inp.outputFormatForBus_(0)
        try:
            log("输入格式 ch=%s rate=%s" % (fmt.channelCount(), fmt.sampleRate()))
            if fmt is None or fmt.channelCount() < 1 or fmt.sampleRate() < 8000:
                push_js(h, {"type": "micstate", "on": False,
                            "msg": "拿不到麦克风输入（没权限或没接麦）：检查 系统设置→隐私与安全→麦克风"})
                return
        except Exception as fe:
            log("格式检查异常: " + repr(fe))
        def onBuf(buf, when):
            try:
                req.appendAudioPCMBuffer_(buf)
            except Exception:
                pass
        inp.installTapOnBus_bufferSize_format_block_(0, 1024, fmt, onBuf)
        ok, err = engine.startAndReturnError_(None)
        log("音频引擎启动 ok=%s err=%s" % (ok, err))
        if not ok:
            push_js(h, {"type": "micstate", "on": False, "msg": "音频引擎启动失败：%s" % err})
            return
        def onRes(result, err):
            try:
                if _tts.get("speaking") or (time.time() - (_tts.get("last_end") or 0.0) < 0.8):
                    return                      # 雪团正在念 / 刚念完，别把自己听进去
                if err is not None:
                    es = str(err)
                    log("识别回调 err=%s" % es[:200])
                    # 我们自己 cancel（收麦 / 雪团开口）时，系统回的就是 216 / 203 / cancel 这类「已取消」，
                    # 那不是故障。以前这里会弹「识别失败：Error Domain=kAFAssistantErrorDomain Code=216」——
                    # 一串英文报错糊在脸上，用户还会把它当提问发出去。
                    if (_mic_closing[0] or ("216" in es) or ("203" in es)
                            or ("cancel" in es.lower())):
                        return
                    if ("1110" in es or "asset" in es.lower()
                            or "not available" in es.lower() or "209" in es):
                        push_js(h, {"type": "micstate", "on": False,
                                    "msg": T("micAsset", lang=L()["name"])})
                        _open_sysprefs("dict")
                    else:
                        push_js(h, {"type": "micstate", "on": False, "msg": T("micFail")})
                    stop_mic(h)
                    return
                if result is None:
                    return
                t = result.bestTranscription().formattedString()
                if not t:
                    return
                if _is_echo(t):
                    log("识别结果像回声，丢弃: %s" % t[:40])
                    return
                if result.isFinal():
                    log("识别完成: %s" % t)
                    _mic["text"] = t
                    push_js(h, {"type": "transcript", "text": t, "auto": True})
                    _focus_main()               # 说完把窗口抢回来，回车才发得出去
                    stop_mic(h)
                else:
                    # 部分结果：实时填进输入框，让人看到在听。
                    # 记下「最后一次真的变了」的时间 —— 识别器会把同一句反复推，
                    # 只有文本变了才算还在说话（静音判定就靠它）。
                    if t != (_mic.get("text") or ""):
                        _mic["text"] = t
                        _mic["t_change"] = time.time()
                    push_js(h, {"type": "transcript", "text": t, "auto": False})
            except Exception as ce:
                log("识别回调异常: " + repr(ce))
        task = rec.recognitionTaskWithRequest_resultHandler_(req, onRes)
        _mic["task"] = task
        _mic["engine"] = engine
        _mic["req"] = req
        _mic["rec"] = rec
        log("_begin_mic 成功，开始聆听")
        _mic_wanted[0] = True
        push_js(h, {"type": "micstate", "on": True,
                    "msg": None if quiet else T("micOk")})
        _mic["t_start"] = time.time()
        _mic["t_change"] = None
        _mic["text"] = ""
        tm = threading.Timer(0.4, lambda: _mic_watch(h))
        tm.daemon = True
        tm.start()
        _mic["timer"] = tm
    except Exception as e:
        log("_begin_mic 失败: " + repr(e))
        push_js(h, {"type": "micstate", "on": False, "msg": "麦克风启动失败：" + str(e)[:90]})


def _norm_echo(t):
    """回声比对用的归一化：去掉标点空格，全角半角不管。"""
    return re.sub(r"[\s，。？！、,.?!:;；：\"'“”‘’\-—…·（）()]+", "", str(t or "")).lower()


def _is_echo(t):
    """这段识别结果是不是雪团自己刚念出来的话？
    语音识别会把「雪团」听成「集团」这类近音字，所以不能做精确比对，
    用「互相包含 + 相似度」两条判据。"""
    last = _tts.get("last_text") or ""
    a, b = _norm_echo(t), _norm_echo(last)
    if len(a) < 6 or not b:
        return False
    if a in b or b in a:
        return True
    try:
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.62
    except Exception:
        return False


def _mic_hold():
    """雪团要开口了 —— 先把耳朵捂上。
    不捂的后果（实测）：它把自己念的话听进去，识别结果被拼进输入框，
    人一按回车就把「雪团刚才说过的话」当成提问发回去，回答于是越来越乱。"""
    if not _mic.get("engine"):
        return False
    _mic_closing[0] = True            # 这次 cancel 引起的错误同样不是故障
    try:
        if _mic.get("task") is not None:
            _mic["task"].cancel()
    except Exception:
        pass
    try:
        if _mic.get("req") is not None:
            _mic["req"].endAudio()
    except Exception:
        pass
    try:
        _mic["engine"].stop()
        _mic["engine"].inputNode().removeTapOnBus_(0)
    except Exception:
        pass
    try:
        tm = _mic.get("timer")
        if tm is not None:
            tm.cancel()
    except Exception:
        pass
    _mic.clear()
    if _mic_wanted[0]:
        push_js(_KEEP.get("handler"),
                {"type": "micstate", "on": False, "hold": True, "msg": T("micHold")})
    log("雪团开口 → 麦克风暂停")
    return True


_MIC_SILENCE = 1.7      # 安静这么久就当这句说完了
_MIC_MAX = 30.0         # 硬上限，兜底


def _mic_watch(h):
    """每 0.4s 巡检一次：安静够久就自动收麦（并把最后一版文本当最终结果推下去，
    界面上出现「按回车发给我」），最多听 30 秒。

    实测 SFSpeechRecognizer 常常一直只吐中间结果、不给最终结果：
    麦克风于是永远停不下来，识别文本一路往上叠加（连雪团自己的声音都被叠进去），
    人一按回车发出去的就是这坨越来越长的脏句子 —— 回答于是越来越乱。"""
    if not _mic.get("engine"):
        return                          # 已经关了
    now = time.time()
    txt = _mic.get("text") or ""
    last = _mic.get("t_change") or _mic.get("t_start") or now
    if txt and (now - last) >= _MIC_SILENCE:
        log("安静 %.1fs（%d 字）→ 自动收麦" % (now - last, len(txt)))
        stop_mic(h, final_text=txt)
        return
    if (now - (_mic.get("t_start") or now)) >= _MIC_MAX:
        log("麦克风超时自动关闭（%.0fs）" % _MIC_MAX)
        stop_mic(h, final_text=txt or None)
        return
    tm = threading.Timer(0.4, lambda: _mic_watch(h))
    tm.daemon = True
    tm.start()
    _mic["timer"] = tm


def _mic_release():
    """说完话把耳朵还回来（前提是用户本来就开着听）。"""
    if not _mic_wanted[0] or _mic.get("engine"):
        return
    h = _KEEP.get("handler")
    if h is None:
        return
    log("雪团说完 → 麦克风恢复")
    _begin_mic(h, quiet=True)


def stop_mic(h, final_text=None):
    """收麦。final_text 非空时把它当「最终识别结果」推下去 ——
    于是界面上出现「按回车发给我」，并且把窗口抢回键盘焦点
    （窗口不是 key window 时，按回车会被送给别的 App，表现就是「回车不灵」）。"""
    _mic_closing[0] = True            # 先立旗：随后系统回的错误都是我们自己取消引起的
    try:
        tm = _mic.get("timer")
        if tm is not None:
            tm.cancel()
    except Exception:
        pass
    try:
        if _mic.get("task") is not None:
            _mic["task"].cancel()
    except Exception:
        pass
    try:
        if _mic.get("req") is not None:
            _mic["req"].endAudio()
    except Exception:
        pass
    try:
        if _mic.get("engine") is not None:
            _mic["engine"].stop()
            _mic["engine"].inputNode().removeTapOnBus_(0)
    except Exception:
        pass
    _mic.clear()
    _mic_wanted[0] = False
    if final_text:
        push_js(h, {"type": "transcript", "text": final_text, "auto": True})
        _focus_main()
    push_js(h, {"type": "micstate", "on": False, "msg": T("micStop")})


# ---------- 消息桥 ----------
class PetHandler(NSObject):
    def initWithWin_(self, win):
        self = objc.super(PetHandler, self).init()
        self.web = None
        self.win = win
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            body = _as_dict(message.body())
            if not body:
                log("收到空/非法消息: " + repr(message.body())[:80])
                return
            t = body.get("type")
            log("收到消息 type=%s keys=%s" % (t, list(body.keys())))
            if t == "hello":
                # 页面就绪：语言包 / 季节 / 语音开关 一起推下去（含场景窗）
                log("收到 hello，推送初始状态 lang=%s" % _lang["now"])
                _PET_HOT["hello"] = True
                try:
                    _refresh_hotzone(self.web)      # 页面活了才问得到热区坐标
                except Exception:
                    pass
                _push_scene({"type": "season", "name": _season["now"]})
                push_js(self, {"type": "i18n", "pack": _ui_pack()})
                push_js(self, {"type": "season", "name": _season["now"]})
                push_js(self, {"type": "ttsstate", "on": _tts["on"]})
                if _nap["on"]:
                    _push_scene({"type": "reststate", "on": True, "msg": T("restOn")})
            elif t == "season":
                set_season(str(body.get("name") or ""), self)
            elif t == "tts":
                set_tts(bool(body.get("on")), self)
            elif t == "lang":
                set_lang(str(body.get("code") or "zh"), self)
            elif t == "langnext":
                i = _LANG_ORDER.index(_lang["now"])
                set_lang(_LANG_ORDER[(i + 1) % len(_LANG_ORDER)], self)
            elif t == "help":
                push_js(self, {"type": "help", "msg": T("help")})
            elif t == "undo":
                do_untidy(self)
            elif t == "scan":
                do_scan(self)
            elif t == "tidy":
                do_tidy(self)
            elif t == "open":
                do_open(self, body.get("app", ""))
            elif t == "time":
                do_time(self)
            elif t == "joke":
                do_joke(self)
            elif t == "chat":
                _chat_guard(body.get("text", ""), self)
            elif t == "focus":
                focus_app(self)
            elif t == "mic":
                start_mic(self)
            elif t == "micstop":
                stop_mic(self)
            elif t == "rest":
                set_rest(bool(body.get("on")), self)
            elif t == "act":
                do_action(self, body.get("name"))
        except Exception as e:
            push_js(self, {"type": "err", "msg": "出错了：" + str(e)})


# ---------- 自检 ----------
def _pump(seconds):
    try:
        from Foundation import NSRunLoop, NSDate
        loop = NSRunLoop.currentRunLoop()
        end = time.time() + seconds
        while time.time() < end:
            loop.runMode_beforeDate_("NSDefaultRunLoopMode", NSDate.dateWithTimeIntervalSinceNow_(0.1))
    except Exception:
        pass


def _probe(web, label, show_win=True):
    pid = os.getpid()
    if show_win:
        try:
            from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID)
            mine = [w for w in (CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID) or [])
                    if w.get("kCGWindowOwnerPID") == pid]
            print("[selftest] 本进程窗口数 =", len(mine))
            for w in mine:
                b = w.get("kCGWindowBounds") or {}
                print("           layer=%s %sx%s onscreen=%s" % (w.get("kCGWindowLayer"),
                      int(b.get("Width", 0)), int(b.get("Height", 0)), w.get("kCGWindowIsOnscreen")))
        except Exception as e:
            print("[selftest] 窗口枚举失败:", e)
    box = {}
    js = ("(function(){var v=document.getElementById('vA');return JSON.stringify({"
          "title:document.title, rs:v?v.readyState:-1, vw:v?v.videoWidth:0, vh:v?v.videoHeight:0,"
          "cur:v?+v.currentTime.toFixed(2):-1, err:(v&&v.error)?v.error.code:0,"
          "paused:v?v.paused:null, w:innerWidth, h:innerHeight});})()")
    try:
        web.evaluateJavaScript_completionHandler_(js, lambda r, e: box.update(r=r, e=e))
        _pump(1.5)
        print("[selftest] %s 页面 = %s" % (label, box.get("r")))
    except Exception as e:
        print("[selftest] JS 求值失败:", e)


def _probe_pet(web, label):
    box = {}
    js = ("(function(){var z=document.getElementById('petZone'),c=document.getElementById('cmd');"
          "return JSON.stringify({mode:document.documentElement.className, w:innerWidth, h:innerHeight,"
          "hasZone:!!z, hasCmd:!!c, hasInput:!!document.getElementById('cmdin'),"
          "hasMic:!!document.getElementById('mic'),"
          "bg:getComputedStyle(document.documentElement).backgroundColor,"
          "bodyBg:getComputedStyle(document.body).backgroundColor,"
          "zoneRect:z?(z.offsetLeft+','+z.offsetTop+','+z.offsetWidth+'x'+z.offsetHeight):'-'});})()")
    try:
        web.evaluateJavaScript_completionHandler_(js, lambda r, e: box.update(r=r, e=e))
        _pump(1.5)
        print("[selftest] %s 交互 = %s" % (label, box.get("r")))
    except Exception as e:
        print("[selftest] JS 求值失败:", e)



def _post_click(x, y, h, tap=None):
    """合成真实鼠标点击。
    注意：Quartz 全局坐标原点在【左下角】，而我们算的是左上角坐标，必须翻转 y。
    """
    try:
        from Quartz import (CGEventCreateMouseEvent, CGEventPost, kCGHIDEventTap,
                            kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp)
        pt = (float(x), float(h - y))
        t0 = kCGHIDEventTap if tap is None else tap
        for e in (kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp):
            CGEventPost(t0, CGEventCreateMouseEvent(None, e, pt, 0))
        return True
    except Exception as e:
        print("[clicktest] 无法合成点击:", e)
        return False


def _probe_click(web):
    box = {}
    js = ("(function(){var c=document.getElementById('cmd'),h=document.getElementById('hint');"
          "var r=c.getBoundingClientRect(),cs=getComputedStyle(c);"
          "return JSON.stringify({cmdClass:c.className,opacity:cs.opacity,"
          "bg:cs.backgroundColor,display:cs.display,"
          "rect:[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)],"
          "hintClass:h.className,active:document.hasFocus(),"
          "mode:document.documentElement.className});})()")
    try:
        web.evaluateJavaScript_completionHandler_(js, lambda r, e: box.update(r=r, e=e))
        _pump(1.5)
        print("[clicktest] 点击后状态 = %s" % box.get("r"))
    except Exception as e:
        print("[clicktest] JS 求值失败:", e)


def _dump_stack(x, y, mypid):
    """打印点击那一刻，这个点上从前往后的窗口栈"""
    try:
        from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
                            kCGNullWindowID)
        ws = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
        rows = []
        for w in ws:
            b = w.get('kCGWindowBounds') or {}
            bx, by, bw, bh = b.get('X', 0), b.get('Y', 0), b.get('Width', 0), b.get('Height', 0)
            if bx <= x <= bx + bw and by <= y <= by + bh:
                rows.append((w.get('kCGWindowLayer'), w.get('kCGWindowOwnerPID'),
                             w.get('kCGWindowOwnerName'), int(bw), int(bh)))
        rows.sort(key=lambda r: -r[0])
        print("[clicktest] 点击时的窗口栈（前→后）:")
        for r in rows:
            tag = "  <== 我们的" if r[1] == mypid else ""
            print("    layer=%-14s pid=%-7s %-14s %sx%s%s" % (r[0], r[1], r[2], r[3], r[4], tag))
    except Exception as e:
        print("[clicktest] 栈枚举失败:", e)


# 菜单栏文案（跟着语言变）
_MENU_TXT = {
    "zh": {"call": "唤起指令栏", "tts": "语音回复（念给我听）", "season": "换背景",
           "pass": "鼠标穿透（不挡桌面图标）",
           "lang": "切换语言", "rest": "休息提醒", "undo": "撤销上次整理",
           "quit": "退出雪团", "off": "关", "restFmt": "{m} 分钟", "nap": "让雪团休息"},
    "en": {"call": "Show command bar", "tts": "Speak replies out loud", "season": "Change scene",
           "pass": "Click-through (don't block icons)",
           "lang": "Language", "rest": "Break reminder", "undo": "Undo last tidy",
           "quit": "Quit Xuetuan", "off": "Off", "restFmt": "{m} min", "nap": "Let Xuetuan nap"},
    "es": {"call": "Mostrar barra", "tts": "Responder en voz alta", "season": "Cambiar fondo",
           "pass": "Transparencia al clic",
           "lang": "Idioma", "rest": "Aviso de descanso", "undo": "Deshacer último orden",
           "quit": "Salir", "off": "Apagado", "restFmt": "{m} min", "nap": "Que Xuetuan duerma"},
    "fr": {"call": "Afficher la barre", "tts": "Répondre à voix haute", "season": "Changer de décor",
           "pass": "Clic traversant",
           "lang": "Langue", "rest": "Pause rappel", "undo": "Annuler le rangement",
           "quit": "Quitter", "off": "Off", "restFmt": "{m} min", "nap": "Xuetuan fait la sieste"},
    "pt": {"call": "Mostrar barra", "tts": "Responder em voz alta", "season": "Trocar cenário",
           "pass": "Clique transparente",
           "lang": "Idioma", "rest": "Aviso de pausa", "undo": "Desfazer última organização",
           "quit": "Sair", "off": "Desligado", "restFmt": "{m} min", "nap": "Xuetuan tirar uma soneca"},
    "ja": {"call": "入力バーを表示", "tts": "声で読み上げる", "season": "背景を変更",
           "pass": "クリックを透過（アイコンを邪魔しない）",
           "lang": "言語", "rest": "休憩リマインド", "undo": "直前の整理を元に戻す",
           "quit": "終了", "off": "オフ", "restFmt": "{m}分", "nap": "雪団を休ませる"},
    "ko": {"call": "입력창 열기", "tts": "소리로 읽어주기", "season": "배경 바꾸기",
           "pass": "클릭 통과(아이콘 안 가리기)",
           "lang": "언어", "rest": "휴식 알림", "undo": "마지막 정리 되돌리기",
           "quit": "종료", "off": "끔", "restFmt": "{m}분", "nap": "설단 잠재우기"},
}


def _m(k, **kw):
    s = _MENU_TXT.get(_lang["now"], _MENU_TXT["zh"]).get(k, k)
    for a, b in kw.items():
        s = s.replace("{%s}" % a, str(b))
    return s


class _StatusBar(NSObject):
    """菜单栏图标的 action target。方法名加 xt 前缀，避免撞系统私有 selector（已踩过坑）。"""

    def xtPing_(self, sender):
        try:
            web = _KEEP.get("web")
            if web is None:
                return
            web.evaluateJavaScript_completionHandler_(
                "document.getElementById('petZone').click()", None)
            print("[雪团] 菜单栏 -> " + _m("call"))
        except Exception as e:
            print("[雪团] 唤起失败:", e)

    def xtTts_(self, sender):
        on = not _tts["on"]
        set_tts(on, _KEEP.get("handler"), notify=True)
        _install_statusbar()

    def xtSeason_(self, sender):
        try:
            name = str(sender.representedObject())
        except Exception:
            name = ""
        set_season(name, _KEEP.get("handler"))

    def xtLang_(self, sender):
        try:
            code = str(sender.representedObject())
        except Exception:
            code = "zh"
        set_lang(code, _KEEP.get("handler"))

    def xtRest_(self, sender):
        try:
            mins = int(str(sender.representedObject()))
        except Exception:
            mins = 0
        _conf["rest"] = mins
        _save_conf()
        _arm_rest(mins)
        _install_statusbar()

    def xtUndo_(self, sender):
        do_untidy(_KEEP.get("handler"))

    def xtPass_(self, sender):
        """鼠标穿透开关。关掉 = 宠物窗常驻可点（老行为），
        代价是它盖住的那一块桌面图标点不动。"""
        _conf["passthrough"] = not _conf.get("passthrough", True)
        _save_conf()
        try:
            w = _KEEP.get("pet_win")
            if w is not None and not _conf["passthrough"]:
                w.setIgnoresMouseEvents_(False)
        except Exception:
            pass
        log("鼠标穿透 = %s" % _conf["passthrough"])
        _install_statusbar()

    def xtNap_(self, sender):
        set_rest(not _nap["on"], _KEEP.get("handler"))
        _install_statusbar()

    def xtQuit_(self, sender):
        print("[雪团] 菜单栏 -> 退出")
        _shutdown()
        try:
            NSApp.terminate_(None)
        except Exception:
            os._exit(0)


def _shutdown():
    """退出前收干净：停麦克风、停朗读、撤掉所有定时器。
    少了这步，退出后 afplay 还会把上一句念完、定时器线程也还挂着。"""
    try:
        stop_mic(_KEEP.get("handler"))
    except Exception:
        pass
    try:
        stop_speak()
    except Exception:
        pass
    try:
        for t in list(_timers.get("remind") or []):
            t.cancel()
        _timers["remind"] = []
    except Exception:
        pass
    try:
        t = _timers.get("rest")
        if t is not None:
            t.cancel()
        _timers["rest"] = None
    except Exception:
        pass
    try:
        _save_conf()
    except Exception:
        pass
    log("=== 雪团退出，资源已回收 ===")


def _mk_item(tgt, title, sel, rep=None, state=None):
    from AppKit import NSMenuItem
    mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel or "", "")
    if sel:
        mi.setTarget_(tgt)
    if rep is not None:
        mi.setRepresentedObject_(str(rep))
    if state is not None:
        mi.setState_(1 if state else 0)
    return mi


def _install_statusbar():
    """菜单栏图标：菜单栏不受访达桌面层影响，一定能点。
    既是「点不动猫」的兜底入口，也是退出入口。切语言时会重建（只换菜单，不重复占位）。"""
    try:
        from AppKit import NSStatusBar, NSMenu, NSMenuItem, NSVariableStatusItemLength
    except Exception as e:
        print("[雪团] 菜单栏不可用:", e)
        return None
    try:
        tgt = _KEEP.get("status_target")
        item = _KEEP.get("status_item")
        if tgt is None:
            tgt = _StatusBar.alloc().init()
            _KEEP["status_target"] = tgt
        if item is None:
            item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
            btn = item.button()
            if btn is not None:
                btn.setTitle_("\U0001F431")
            _KEEP["status_item"] = item

        menu = NSMenu.alloc().init()
        menu.addItem_(_mk_item(tgt, _m("call"), "xtPing:"))
        menu.addItem_(_mk_item(tgt, _m("tts"), "xtTts:", state=_tts["on"]))
        menu.addItem_(_mk_item(tgt, _m("pass"), "xtPass:",
                               state=bool(_conf.get("passthrough", True))))
        menu.addItem_(_mk_item(tgt, _m("nap"), "xtNap:", state=_nap["on"]))

        # 换背景子菜单
        sub = NSMenu.alloc().init()
        for key in _SEASONS:
            mi_s = _mk_item(tgt, L()["seasons"][key], "xtSeason:", rep=key,
                            state=(key == _season["now"]))
            sub.addItem_(mi_s)
        mi_season = _mk_item(tgt, _m("season"), None)
        mi_season.setSubmenu_(sub)
        menu.addItem_(mi_season)

        # 语言子菜单（7 种）
        sub_l = NSMenu.alloc().init()
        for code in _LANG_ORDER:
            mi_l = _mk_item(tgt, LANGS[code]["name"], "xtLang:", rep=code,
                            state=(code == _lang["now"]))
            sub_l.addItem_(mi_l)
        mi_lang = _mk_item(tgt, _m("lang"), None)
        mi_lang.setSubmenu_(sub_l)
        menu.addItem_(mi_lang)

        # 休息提醒子菜单（关 / 30 / 45 / 60）
        sub_r = NSMenu.alloc().init()
        now_r = int(_conf.get("rest") or 0)
        for mins in (0, 30, 45, 60):
            label = _m("off") if mins == 0 else _m("restFmt", m=mins)
            sub_r.addItem_(_mk_item(tgt, label, "xtRest:", rep=mins, state=(mins == now_r)))
        mi_rest = _mk_item(tgt, _m("rest"), None)
        mi_rest.setSubmenu_(sub_r)
        menu.addItem_(mi_rest)

        menu.addItem_(_mk_item(tgt, _m("undo"), "xtUndo:"))
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(_mk_item(tgt, _m("quit"), "xtQuit:"))
        item.setMenu_(menu)
        return item
    except Exception as e:
        print("[雪团] 菜单栏图标安装失败:", e)
        log("菜单栏安装失败: " + repr(e))
        return None


def _probe_say(web):
    box = {}
    js = ("(function(){var s=document.getElementById('say');"
          "return JSON.stringify({sayClass:s.className,"
          "sayText:(s.textContent||'').slice(0,200)});})()")
    try:
        web.evaluateJavaScript_completionHandler_(js, lambda r, e: box.update(r=r, e=e))
        _pump(2)
        print("[chattest] 气泡 =", box.get("r"))
        log("chattest 气泡 = " + str(box.get("r")))
    except Exception as e:
        print("[chattest] JS 求值失败:", e)
        log("chattest JS 失败: " + repr(e))


def _probe_diag(web):
    """逐项诊断：JS 侧到底有没有接住原生回传。"""
    def ev(js, tag):
        box = {}

        def cb(r, e):
            box["r"] = r
            box["e"] = (repr(e) if e else None)

        try:
            web.evaluateJavaScript_completionHandler_(js, cb)
        except Exception as ex:
            box["e"] = "python:" + repr(ex)
        _pump(1.5)
        line = "[diag] %s -> r=%s e=%s" % (tag, box.get("r"), box.get("e"))
        print(line)
        log(line)
    ev("typeof window.onPetResult", "typeof onPetResult")
    ev("document.readyState", "readyState")
    ev("window.__jsErr || '(无捕获到的错误)'", "页面JS错误")
    ev("(function(){try{window.onPetResult({type:'chat',msg:'手动测试'});"
       "return 'called'}catch(e){return 'THROW:'+e.message}})()", "手动调用 onPetResult")
    ev("document.getElementById('say').textContent", "气泡文本")
    ev("document.getElementById('say').className", "气泡class")


def _make_config(with_handler):
    cfg = WKWebViewConfiguration.alloc().init()
    try:
        prefs = cfg.preferences()
        if prefs is None:
            from WebKit import WKPreferences
            prefs = WKPreferences.alloc().init()
            cfg.setPreferences_(prefs)
        if hasattr(prefs, "setPlaysInlineVideosEnabled_"):
            prefs.setPlaysInlineVideosEnabled_(True)
        for k in ("_requiresUserActionForMediaPlayback", "_requiresUserActionForAudioPlayback",
                  "_allowsInlineMediaPlayback"):
            try:
                prefs.setValue_forKey_(False, k)
            except Exception:
                pass
        try:
            cfg.setValue_forKey_(0, "_mediaTypesRequiringUserActionForPlayback")
        except Exception:
            pass
    except Exception:
        pass
    if with_handler:
        uc = WKUserContentController.alloc().init()
        cfg.setUserContentController_(uc)
        return cfg, uc
    return cfg, None


def _file_url(html, mode):
    """给同一份 HTML 加 ?win=scene / ?win=pet 查询参数，决定加载哪套 UI。"""
    base = NSURL.fileURLWithPath_isDirectory_(html, False)
    url = NSURL.URLWithString_relativeToURL_("?win=" + mode, base)
    return url, base.URLByDeletingLastPathComponent()


def _window(w, h, level, ignores_mouse, key_ok):
    cls = PetWindow if key_ok else NSWindow
    win = cls.alloc().initWithContentRect_styleMask_backing_defer_(
        ((0, 0), (w, h)), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    win.setLevel_(level)
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorFullScreenAuxiliary)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setIgnoresMouseEvents_(ignores_mouse)
    win.setHasShadow_(False)
    win.setMovable_(False)
    return win


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="桌面伴侣-雪团-壁纸.html")
    ap.add_argument("--selftest", type=int, default=0)
    ap.add_argument("--micdebug", type=int, default=0,
                    help="在 .app 环境里查/申请语音+麦克风权限，结果写日志")
    ap.add_argument("--seasontest", type=int, default=0,
                    help="依次切四季，验证背景图加载/粒子/TTS")
    ap.add_argument("--msgtest", type=int, default=0,
                    help="从 JS 真的发一条 postMessage，验证 JS→原生→回传气泡 整条环")
    ap.add_argument("--chattest", type=int, default=0,
                    help="直接调 DeepSeek 聊天，验证「请求→回传→气泡」整条链路")
    ap.add_argument("--langtest", type=int, default=0,
                    help="依次切 7 种语言，验证文案/嗓音/识别语言/指令词")
    ap.add_argument("--streamtest", type=int, default=0,
                    help="流式聊天自检：验证 chatstart→chatdelta→chatend 与气泡逐步增长")
    ap.add_argument("--memtest", type=int, default=0,
                    help="记忆与提醒自检：记名字/记事实/设提醒")
    ap.add_argument("--uitest", type=int, default=0,
                    help="界面自检：快捷指令/语言键/文案是否真的换掉了")
    ap.add_argument("--lang", default=None, help="启动时指定语言 zh/en/es/fr/pt/ja/ko")
    ap.add_argument("--clicktest", type=int, default=0,
                    help="在猫身上模拟一次真实鼠标点击，验证点击是否到达宠物窗")
    ap.add_argument("--petlevel", type=int, default=None,
                    help="强制指定宠物窗层级（调试用）")
    ap.add_argument("--policy", default="accessory", choices=["accessory", "regular"],
                    help="激活策略：accessory(不进Dock) / regular(普通App)")
    a, _ = ap.parse_known_args()
    log("=== 启动 argv=%s ===" % sys.argv[1:])

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular
                             if a.policy == "regular"
                             else NSApplicationActivationPolicyAccessory)
    print("[雪团] 激活策略 =", a.policy)

    HERE = os.path.dirname(os.path.abspath(__file__))
    html = a.html if os.path.isabs(a.html) else os.path.join(HERE, a.html)
    if not os.path.exists(html):
        print("[雪团] 找不到页面：%s" % html)
        sys.exit(1)

    screen = NSScreen.mainScreen().frame()
    w, h = int(screen.size.width), int(screen.size.height)
    petw = int(w * 0.40)
    print("[雪团] 屏幕 %dx%d，宠物窗宽 %d" % (w, h, petw))

    # 场景窗（桌面层，忽略鼠标）
    s_cfg, _ = _make_config(False)
    s_web = WKWebView.alloc().initWithFrame_configuration_(((0, 0), (w, h)), s_cfg)
    s_web.setWantsLayer_(True)
    for _k in ("drawsBackground", "_drawsBackground"):
        try:
            s_web.setValue_forKey_(False, _k)
        except Exception:
            pass
    s_url, s_dir = _file_url(html, "scene")
    s_web.loadFileURL_allowingReadAccessToURL_(s_url, s_dir)
    s_win = _window(w, h, LEVELS["desktop"], True, False)
    s_win.setContentView_(s_web)
    s_win.orderFrontRegardless()
    _KEEP["scene_web"] = s_web

    # 宠物窗（图标之上，可点）
    p_cfg, p_uc = _make_config(True)
    p_web = WKWebView.alloc().initWithFrame_configuration_(((0, 0), (petw, h)), p_cfg)
    p_web.setWantsLayer_(True)
    for _k in ("drawsBackground", "_drawsBackground"):
        try:
            p_web.setValue_forKey_(False, _k)
        except Exception:
            pass
    p_url, p_dir = _file_url(html, "pet")
    p_web.loadFileURL_allowingReadAccessToURL_(p_url, p_dir)
    _pl = a.petlevel if a.petlevel is not None else PET_LEVEL
    print("[雪团] 宠物窗层级 =", _pl)
    p_win = _window(petw, h, _pl, False, True)
    handler = PetHandler.alloc().initWithWin_(p_win)
    p_uc.addScriptMessageHandler_name_(handler, "pet")
    p_web.setWebViewUIDelegate_(handler) if hasattr(p_web, "setWebViewUIDelegate_") else None
    p_win.setContentView_(p_web)
    p_win.orderFrontRegardless()
    _KEEP["pet_win"] = p_win
    try:
        _arm_click_passthrough(p_win, p_web)
    except Exception as e:
        log("穿透安装异常: " + repr(e))
    handler.web = p_web
    _KEEP["handler"] = handler
    _KEEP["win"] = p_win
    _KEEP["web"] = p_web
    _KEEP["bridge"] = _JSBridge.alloc().initWithWeb_(p_web)
    _load_conf()                       # 语言 / 季节 / 语音 / 休息提醒 / 聊天上下文
    if a.lang:                         # 命令行可临时指定语言
        _conf["lang"] = a.lang
        if a.lang in LANGS:
            _lang["now"] = a.lang
    _load_mem()                        # 名字 / 记住的事
    _tts["on"] = bool(_conf.get("tts"))
    _install_statusbar()
    _arm_rest(int(_conf.get("rest") or 0))
    print("[雪团] 语言=%s 季节=%s 语音回复=%s 休息提醒=%s 分钟"
          % (L()["name"], L()["seasons"][_season["now"]], _tts["on"], _conf.get("rest")))

    if a.micdebug:
        _pump(2)
        log("=== micdebug 开始 (app 环境) ===")
        print("[micdebug] 查询权限…")
        try:
            from Speech import SFSpeechRecognizer
            log("语音识别权限=%s (0未决 1受限 2拒绝 3已授权)"
                % SFSpeechRecognizer.authorizationStatus())
            r0 = SFSpeechRecognizer.alloc().init()
            log("识别器可用=%s" % r0.isAvailable())
        except Exception as e:
            log("语音框架异常: " + repr(e))
        log("麦克风权限=%s (0未决 1受限 2拒绝 3已授权)" % _mic_permission())
        log("--- 调用 start_mic（未决会弹权限框）---")
        start_mic(handler)
        _pump(30)
        log("=== micdebug 结束 ===")
        os._exit(0)

    if a.seasontest:
        sw = _KEEP.get("scene_web")
        _pump(4)
        log("=== seasontest 开始 ===")

        def probe(tag):
            box = {}

            def cb(r, e):
                box["r"] = r
                box["e"] = repr(e) if e else None
            js = ("(function(){var a=document.getElementById('bgA'),b=document.getElementById('bgB');"
                  "var p=document.getElementById('particles');"
                  "return JSON.stringify({season:document.documentElement.getAttribute('data-season'),"
                  "aW:a.naturalWidth,aOp:a.style.opacity||'0',bW:b.naturalWidth,bOp:b.style.opacity||'0',"
                  "show:(String(a.style.opacity)==='1'?a:(String(b.style.opacity)==='1'?b:null))"
                  "?String(a.style.opacity)==='1'?a.src.split('/').pop():b.src.split('/').pop():'(无)',"
                  "n:p?p.children.length:0,"
                  "vid:document.getElementById('vA').style.opacity||'0'});})()")
            try:
                sw.evaluateJavaScript_completionHandler_(js, cb)
            except Exception as ex:
                box["e"] = repr(ex)
            _pump(2.5)
            line = "[seasontest] %-8s %s" % (tag, box.get("r") or box.get("e"))
            print(line)
            log(line)

        for nm in ("spring", "summer", "autumn", "winter"):
            set_season(nm, handler)
            _pump(1.5)
            probe(nm)

        # 顺带验一下 TTS 链路
        log("--- 验 TTS ---")
        set_tts(True, handler)
        speak("你好呀，我是雪团")
        _pump(9)
        log("=== seasontest 结束 ===")
        os._exit(0)

    if a.msgtest:
        _pump(4)
        log("=== msgtest 开始 ===")
        # 完全模拟用户行为：由 JS 发 postMessage，走真实消息桥
        js_send = ("window.webkit.messageHandlers.pet.postMessage({type:'time'}); 'sent'")
        def _c1(r, e):
            print("[msgtest] postMessage(time) -> r=%s e=%s" % (r, e))
            log("msgtest postMessage 返回 r=%s e=%s" % (r, e))
        try:
            p_web.evaluateJavaScript_completionHandler_(js_send, _c1)
        except Exception as ex:
            print("[msgtest] 发送异常:", ex)
        _pump(3)
        _probe_say(p_web)          # 应该有报时气泡

        js_chat = ("window.webkit.messageHandlers.pet.postMessage({type:'chat',text:'用一句话打个招呼'}); 'sent'")
        def _c2(r, e):
            print("[msgtest] postMessage(chat) -> r=%s e=%s" % (r, e))
        try:
            p_web.evaluateJavaScript_completionHandler_(js_chat, _c2)
        except Exception as ex:
            print("[msgtest] 发送异常:", ex)
        _pump(20)
        _probe_say(p_web)          # 应该有 DeepSeek 回复

        log("--- 探测麦克风路径 ---")
        try:
            p_web.evaluateJavaScript_completionHandler_(
                "window.webkit.messageHandlers.pet.postMessage({type:'mic'}); 'sent'", None)
        except Exception as ex:
            print("[msgtest] mic 发送异常:", ex)
        _pump(10)
        _probe_say(p_web)
        log("=== msgtest 结束 ===")
        os._exit(0)

    if a.chattest:
        _pump(4)
        log("=== chattest 开始 ===")
        print("[chattest] 直接调用 do_chat('用一句话跟我打个招呼')")
        do_chat(handler, "用一句话跟我打个招呼")
        _pump(20)
        _probe_say(p_web)
        _probe_diag(p_web)
        log("=== chattest 结束 ===")
        os._exit(0)

    if a.langtest:
        _pump(3)
        log("=== langtest 开始 ===")
        for code in _LANG_ORDER:
            set_lang(code, handler, notify=False)
            _pump(0.5)
            line = "[langtest] %-3s %-9s 嗓音=%-9s 春=%-9s 提示=%s" % (
                code, LANGS[code]["name"], _pick_voice(),
                L()["seasons"]["spring"], T("hint")[:46])
            print(line)
            log(line)
        set_lang("zh", handler)
        _pump(1)
        _probe_say(p_web)
        log("=== langtest 结束 ===")
        os._exit(0)

    if a.streamtest:
        _pump(3)
        log("=== streamtest 开始 ===")
        do_chat(handler, "用三句话介绍一下你自己")
        for i in range(7):
            _pump(2)
            _probe_say(p_web)
        log("=== streamtest 结束 ===")
        os._exit(0)

    if a.memtest:
        _pump(3)
        log("=== memtest 开始 ===")
        for s in ("我叫 Bill", "记住我不喝咖啡", "我叫什么", "10分钟后提醒我喝水"):
            do_chat(handler, s)
            _pump(2)
            _probe_say(p_web)
        log("提醒解析 zh=%s" % str(_parse_remind("10分钟后提醒我喝水")))
        log("提醒解析 en=%s" % str(_parse_remind("remind me to drink water in 5 minutes")))
        log("提醒解析 无时间=%s" % str(_parse_remind("提醒我喝水")))
        log("记忆 = %s" % json.dumps(_mem, ensure_ascii=False))
        log("=== memtest 结束 ===")
        os._exit(0)

    if a.uitest:
        _pump(4)
        log("=== uitest 开始 ===")

        def uiprobe(tag):
            box = {}
            js = ("(function(){var q=function(i){return !!document.getElementById(i)};"
                  "var ch=document.getElementById('chips');"
                  "return JSON.stringify({lang:document.documentElement.lang,"
                  "chips:ch?ch.children.length:-1,"
                  "chipTxt:ch?Array.prototype.map.call(ch.children,function(b){return b.textContent}).join('|'):'',"
                  "btns:['mic','tts','lang','close','cmdsend'].filter(q).join(','),"
                  "ph:document.getElementById('cmdin').placeholder,"
                  "hint:(document.getElementById('hint').textContent||'').slice(0,24),"
                  "planOk:document.getElementById('planOk').textContent});})()")
            try:
                p_web.evaluateJavaScript_completionHandler_(js, lambda r, e: box.update(r=r, e=e))
            except Exception as ex:
                box["e"] = repr(ex)
            _pump(2)
            line = "[uitest] %-6s %s" % (tag, box.get("r") or box.get("e"))
            print(line)
            log(line)

        uiprobe("初始")
        set_lang("en", handler)
        _pump(1.5)
        uiprobe("英文")
        set_lang("ja", handler)
        _pump(1.5)
        uiprobe("日文")
        set_lang("zh", handler)
        _pump(1.5)
        uiprobe("回中文")
        log("=== uitest 结束 ===")
        os._exit(0)

    if a.clicktest:
        _pump(4)
        cx, cy = 0.575 * petw, 0.69 * h          # 猫热区中心（屏幕坐标）
        print("[clicktest] 在猫身上点击 (%.0f, %.0f)" % (cx, cy))
        _dump_stack(cx, cy, os.getpid())
        try:
            NSApp.activateIgnoringOtherApps_(True)
            print("[clicktest] 已强制激活本 App")
        except Exception as e:
            print("[clicktest] 激活失败:", e)
        _pump(1)
        _post_click(cx, cy, h)
        _pump(3)
        print("[clicktest] --- A. 真实鼠标点击后 ---")
        _probe_click(p_web)
        # B. 同样一个处理函数，改由 JS 直接触发，用来区分「点击没送达」还是「JS 坏了」
        try:
            p_web.evaluateJavaScript_completionHandler_(
                "document.getElementById('petZone').click()", None)
        except Exception as e:
            print("[clicktest] 触发失败:", e)
        _pump(2)
        print("[clicktest] --- B. JS 直接触发后 ---")
        _probe_click(p_web)
        os._exit(0)

    if a.selftest:
        print("[雪团] 自检 %d 秒" % a.selftest)
        _pump(4)
        _probe(s_web, "场景")
        _probe_pet(p_web, "宠物")
        _pump(max(0.0, a.selftest - 4))
        _probe(s_web, "场景", False)
        os._exit(0)

    try:
        _sp, _mc = _perms()
        log("启动时权限 语音识别=%s 麦克风=%s (0未决 1受限 2拒绝 3已授权)" % (_sp, _mc))
    except Exception as _e:
        log("启动时权限查询失败: " + repr(_e))

    print("[雪团] 已启动：点左侧雪团说话；退出 = 右上角菜单栏猫头 > %s（或 ⌘Q / 关终端）。" % _m("quit"))
    print("[雪团] 菜单栏猫头里可换背景、换语言（7 种）、开语音回复、设休息提醒、撤销整理。")
    app.run()


if __name__ == "__main__":
    main()
