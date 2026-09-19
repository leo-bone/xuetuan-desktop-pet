<div align="center">

# 🐱 雪团 · Xuetuan

**住进你桌面的一只猫 · An AI cat that lives on your desktop**

一只用 macOS 原生框架（pyobjc + WKWebView）写的轻量桌面伴侣：猫不是浮在桌面上的窗口，而是**长在全屏场景视频里**——四季流转，它就坐在窗边陪着你。支持 7 种语言、语音对话、接大模型、桌面整理，还有「一键让它躺下打哈欠休息」。

A lightweight desktop companion built on native macOS frameworks (pyobjc + WKWebView). The cat isn't a floating window — it's **painted into a full-screen scene video**, sitting by the window through the four seasons. 7 languages, voice chat, LLM-powered conversation, desktop tidying, and a one-tap "nap & yawn" rest mode.

![雪团 · 桌面伴侣 演示 / Demo](xuetuan_demo.gif)

▶️ 高清视频（**含七语言语音**）/ Full-quality video (**with 7-language narration**): [`xuetuan_demo.mp4`](xuetuan_demo.mp4)

[中文](#中文) · [English](#english) · [日本語](#日本語) · [한국어](#한국어) · [Español](#español) · [Português](#português) · [Français](#français)

</div>

---

## 中文

雪团是一只原创卡通猫桌面伴侣，跑在 macOS 上，不依赖 Electron，全程原生 + 一个 WKWebView。它安安静静待在桌面层，你可以随手点它聊天、让它换季节背景、帮你整理桌面，或者干脆让它睡一觉。

### ✨ 功能亮点

| 分类 | 能力 |
| --- | --- |
| 🎬 场景 | 全屏桌面壁纸式陪伴；春樱 / 夏绿 / 秋枫 / 冬雪四季切换（冬季是视频雪景，其余季节图片 + 粒子） |
| 🌐 多语言 | 界面 / 语音 / 识别 / 大模型回答，7 种语言同步切换：中文、English、Español、Français、Português、日本語、한국어 |
| 💬 对话 | 点它说话 → 输入文字或按 🎤 语音（回车发送）；接 DeepSeek 流式吐字，会记住「你的名字」「你的偏好」，还能「10 分钟后提醒我喝水」 |
| 🧹 干活 | 「整理桌面」先扫描、给预览、确认后才动手，可一键撤销；也能「打开 Safari」「现在几点」「讲个笑话」 |
| 😴 **休息** | **点 😴，猫立刻停止转圈，躺下打哈欠入睡**（叠一层打哈欠动画 + 夜色 + 飘起的 zzz）；再点一次或点猫即可唤醒 |
| ✨ **动作菜单** | **点 ✨ 弹出菜单，明码写出雪团会什么：招手问候 / 看风景 / 发呆 / 打哈欠睡觉——点哪条演哪条** |
| 🖱️ 细节 | 鼠标穿透开关（不挡桌面图标）；思考时转个小圈，休息时它自动不转；状态栏猫头菜单是点不动猫时的兜底入口 |

### 🆕 这次新增了什么

1. **😴 休息 = 真的不动了**：点下去主场景先停住（不再转圈），猫**打一次哈欠，然后定格睡着、彻底不动**——之前是循环播打哈欠，严格说还在动，现在改成「一遍 + 定格」，配夜色遮罩和飘起的 zzz。再点一次，或直接点猫，就醒。
2. **✨ 从「随机」改成「动作菜单」**：原来点 ✨ 是随机撞一个动作，点完也不知道它到底能干嘛（这也是那个按钮认不出来的原因）。现在弹出一排**带名字**的按钮，想演哪个点哪个，文案跟着 7 种语言一起变。
3. **😴 / ✨ 两个按钮的外观修好了**：这两个键原来漏写 CSS，吃的是浏览器默认按钮样式，在界面上就是两个认不出的方框。现在和 🎤🔊 同款圆形键，休息时还会呼吸式放大。
4. **演示视频有声音了**：16 秒，七种语言依次问好（中 / 英 / 日 / 韩 / 西 / 葡 / 法），每段用对应的系统真人音色朗读，底下铺一层冬季风声；结尾 3 秒切到「打哈欠 → 睡着」示范休息。
5. **README 加法语**：说明文档补齐 7 种语言（中 / 英 / 日 / 韩 / 西 / 葡 / 法）。
6. **同款菜单栏开关**：菜单栏猫头里的「让雪团休息」，和按钮状态实时同步，重启后还记得。

### 🚀 运行

```bash
# 依赖
pip3 install pyobjc

# 启动（双击也可）
python3 desktop_pet.py
# 或双击：启动桌面挂件.command
```

> 仅支持 macOS。默认加载 `桌面伴侣-雪团-壁纸.html`（由 `build_wallpaper.py` 用 `wallpaper_template.html` 生成）。

---

## English

Xuetuan is an original cartoon-cat desktop companion for macOS. No Electron — native pyobjc plus a single WKWebView. It sits quietly on the desktop layer; tap it to chat, change the season, tidy your desk, or just let it take a nap.

### ✨ Highlights

| Area | What it does |
| --- | --- |
| 🎬 Scene | Full-screen wallpaper-style companion; four seasons (spring sakura / summer green / autumn maple / winter snow). Winter is a video snow scene, the others are images + particles |
| 🌐 Languages | UI, voice, speech recognition and LLM replies all switch together across 7 languages: 中文, English, Español, Français, Português, 日本語, 한국어 |
| 💬 Chat | Click the cat → type or hit 🎤 to speak (Enter to send); streams answers from DeepSeek, remembers your name and preferences, and can "remind me to drink water in 10 minutes" |
| 🧹 Chores | "Tidy desk" scans first, shows a preview, only acts after you confirm, and can undo; also "open Safari", "what time is it", "tell a joke" |
| 😴 **Rest** | **Hit 😴 and the cat stops spinning, lies down and yawns to sleep** (yawn clip + night veil + floating zzz); click it again or tap the cat to wake |
| ✨ **Action menu** | **Hit ✨ to open a menu that names what Xuetuan can do: wave hello / watch the scenery / zone out / yawn & sleep — pick one and it plays** |
| 🖱️ Details | Click-through toggle (won't block desktop icons); a tiny spinner while thinking, auto-hidden while resting; a menu-bar cat icon as a fallback when the cat can't be clicked |

### 🆕 What's new

1. **😴 Rest now means genuinely still** — tapping it pauses the main scene (no more spinning), the cat **yawns once and then freezes, asleep and completely motionless**. It used to loop the yawn, which technically still moved; now it's "play once + hold the last frame", with a night veil and floating zzz. Tap again, or tap the cat, to wake.
2. **✨ went from "random" to an action menu** — it used to fire a random action, so you had no idea what it did (which is exactly why the button was unreadable). Now it opens a row of **labelled** buttons, translated across all 7 languages.
3. **The 😴 / ✨ buttons got their styling back** — they had no CSS at all and fell back to the browser default, i.e. two unidentifiable squares. They now match 🎤🔊, and pulse gently while resting.
4. **The demo video has sound** — 16 seconds, greeting in seven languages (zh / en / ja / ko / es / pt / fr), each read by a matching system voice over a winter-wind bed; the last 3 seconds demonstrate "yawn → asleep".
5. **French added to the README** — all 7 language sections are here now.
6. **Matching menu-bar toggle** — "Let Xuetuan nap", synced with the button and remembered after restart.

### 🚀 Run

```bash
pip3 install pyobjc
python3 desktop_pet.py        # or double-click 启动桌面挂件.command
```

> macOS only. Loads `桌面伴侣-雪团-壁纸.html` by default (generated from `wallpaper_template.html` by `build_wallpaper.py`).

---

## 日本語

雪団（シュエトゥアン）は、macOS 向けのオリジナル猫キャラのデスクトップコンパニオンです。Electron は使わず、pyobjc と WKWebView だけで動く軽量設計。デスクトップ層にそっと居座り、クリックすれば会話、季節の変更、デスクトップの整理、そして「お昼寝」までできます。

### ✨ 主な機能

| 項目 | 内容 |
| --- | --- |
| 🎬 シーン | 全画面の壁紙風コンパニオン。春夏秋冬（春＝桜 / 夏＝緑 / 秋＝紅葉 / 冬＝雪）を切替。冬は動画の雪景色、他は画像＋パーティクル |
| 🌐 多言語 | UI・音声・音声認識・LLM の回答を 7 言語で同時切替：中文・English・Español・Français・Português・日本語・한국어 |
| 💬 会話 | 猫をクリック → 入力、または 🎤 で音声（Enter で送信）。DeepSeek のストリーミング回答、名前や好みを記憶、「10分後に水を飲むよう教えて」も可 |
| 🧹 お手伝い | 「デスクトップを整理」はまずスキャン→プレビュー→確認後に実行、ワンクリックで元に戻せる。「Safari を開いて」「今何時？」「冗談言って」も |
| 😴 **休憩** | **😴 を押すと猫はくるくる回るのをやめ、横になってあくびをして眠る**（あくび映像＋夜のヴェール＋浮かぶ zzz）。もう一度押すか猫をタップで起床 |
| ✨ **アクションメニュー** | **✨ を押すとメニューが開き、できることが明記されます：手を振る / 景色を眺める / ぼーっとする / あくびして寝る。押したものを再生** |
| 🖱️ 細部 | クリック透過スイッチ（アイコンを邪魔しない）。考え中は小さなスピナー、休憩中は自動で停止。メニューバーの猫アイコンはフォールバック入口 |

### 🆕 今回の新機能

1. **😴 休憩は「本当に動かなく」なりました** — 押すとまずメインシーンが停止（もう回りません）、猫は**あくびを一度だけして、そのまま固まって眠り、まったく動きません**。以前はあくびをループ再生していて、厳密にはまだ動いていました。今は「一度再生＋最終フレームで停止」、夜のヴェールと浮かぶ zzz 付き。もう一度押すか猫をタップで起床。
2. **✨ は「ランダム」から「アクションメニュー」へ** — 以前はランダムで動くだけで、何ができるのか分かりませんでした（ボタンが判別できなかった原因でもあります）。今は**名前の付いた**ボタンが並び、7言語で表示されます。
3. **😴 / ✨ ボタンの見た目を修正** — この2つは CSS が抜けていてブラウザ既定の見た目、つまり正体不明の四角になっていました。🎤🔊 と同じ丸ボタンになり、休憩中はゆっくり脈打ちます。
4. **デモ動画に音声が入りました** — 16秒、7言語で挨拶（中・英・日・韓・西・葡・仏）。それぞれ対応するシステム音声で読み上げ、下に冬の風の音。最後の3秒は「あくび → 就寝」の実演です。
5. **README にフランス語を追加** — 7言語すべてそろいました。
6. **メニューバーにも同機能** — 「雪団を休ませる」。ボタンと状態同期、再起動後も記憶。

### 🚀 起動

```bash
pip3 install pyobjc
python3 desktop_pet.py        # または 启动桌面挂件.command をダブルクリック
```

> macOS 専用。既定で `桌面伴侣-雪团-壁纸.html` を読み込みます（`build_wallpaper.py` が `wallpaper_template.html` から生成）。

---

## 한국어

설단(Xuetuan)은 macOS용 오리지널 고양이 캐릭터 데스크톱 컴패니언입니다. Electron 없이 pyobjc와 WKWebView만으로 가볍게 동작합니다. 바탕화면 레이어에 조용히 자리 잡고, 클릭하면 대화·계절 변경·바탕화면 정리, 그리고 낮잠까지 가능합니다.

### ✨ 주요 기능

| 항목 | 내용 |
| --- | --- |
| 🎬 장면 | 전체 화면 배경화면형 컴패니언. 사계절(봄 벚꽃 / 여름 초록 / 가을 단풍 / 겨울 눈) 전환. 겨울은 영상 눈 풍경, 나머지는 이미지 + 파티클 |
| 🌐 다국어 | UI·음성·음성인식·LLM 답변을 7개 언어로 동시 전환: 中文·English·Español·Français·Português·日本語·한국어 |
| 💬 대화 | 고양이 클릭 → 입력 또는 🎤 음성(Enter 전송). DeepSeek 스트리밍 답변, 이름/취향 기억, "10분 뒤에 물 마시라고 알려줘"도 가능 |
| 🧹 심부름 | "바탕화면 정리"는 먼저 스캔→미리보기→확인 후 실행, 원클릭 되돌리기. "Safari 열어", "몇 시야?", "농담해 줘"도 |
| 😴 **휴식** | **😴를 누르면 고양이가 빙글빙글 도는 걸 멈추고 누워 하품하며 잠듭니다**(하품 영상 + 밤 베일 + 떠오르는 zzz). 다시 누르거나 고양이를 탭하면 깨어남 |
| ✨ **동작 메뉴** | **✨를 누르면 메뉴가 열리고 할 수 있는 동작이 이름과 함께 나옵니다: 손 흔들기 / 경치 감상 / 멍때리기 / 하품하고 자기 — 고른 것이 재생됩니다** |
| 🖱️ 디테일 | 클릭 통과 토글(아이콘 안 가림). 생각 중엔 작은 스피너, 휴식 중엔 자동 정지. 메뉴바 고양이 아이콘은 대체 입구 |

### 🆕 이번 업데이트

1. **😴 휴식이 이제 정말로 멈춥니다** — 누르면 먼저 메인 장면이 정지하고(더는 돌지 않음), 고양이는 **하품을 한 번 하고 그대로 굳어 잠들며 전혀 움직이지 않습니다**. 예전에는 하품을 반복 재생해서 엄밀히는 계속 움직였습니다. 지금은 "한 번 재생 + 마지막 프레임 정지"이고 밤 베일과 떠오르는 zzz가 붙습니다. 다시 누르거나 고양이를 탭하면 깨어납니다.
2. **✨가 "무작위"에서 "동작 메뉴"로** — 예전에는 무작위로 하나만 실행해서 뭐 하는 건지 알 수 없었습니다(버튼이 알아볼 수 없었던 이유이기도 합니다). 이제 **이름이 붙은** 버튼이 나오고 7개 언어로 함께 바뀝니다.
3. **😴 / ✨ 버튼 외형 복구** — 이 둘은 CSS가 빠져 브라우저 기본 버튼 모양, 즉 정체불명의 사각형이었습니다. 이제 🎤🔊와 같은 원형 버튼이고 휴식 중에는 천천히 부풀어 오릅니다.
4. **데모 영상에 소리가 들어갔습니다** — 16초, 7개 언어 인사(중·영·일·한·서·포·프). 각 언어에 맞는 시스템 음성으로 읽어 주고 아래에 겨울 바람 소리를 깔았습니다. 마지막 3초는 "하품 → 잠들기" 시연입니다.
5. **README에 프랑스어 추가** — 이제 7개 언어 설명이 모두 있습니다.
6. **메뉴바 동일 토글** — "설단 잠재우기". 버튼과 상태 동기화, 재시작 후에도 기억.

### 🚀 실행

```bash
pip3 install pyobjc
python3 desktop_pet.py        # 또는 启动桌面挂件.command 더블클릭
```

> macOS 전용. 기본으로 `桌面伴侣-雪团-壁纸.html`을 로드합니다(`build_wallpaper.py`가 `wallpaper_template.html`로 생성).

---

## Español

Xuetuan es un compañero de escritorio con forma de gato original para macOS. Sin Electron: solo pyobjc nativo y un WKWebView. Se queda tranquilo en la capa del escritorio; tócalo para charlar, cambiar la estación, ordenar el escritorio o simplemente dejar que eche una siesta.

### ✨ Características

| Área | Qué hace |
| --- | --- |
| 🎬 Escena | Compañero a pantalla completa estilo fondo de pantalla; cuatro estaciones (cerezo en primavera / verde en verano / arce en otoño / nieve en invierno). El invierno es un vídeo nevado; el resto, imagen + partículas |
| 🌐 Idiomas | Interfaz, voz, reconocimiento y respuestas del modelo cambian juntos en 7 idiomas: 中文, English, Español, Français, Português, 日本語, 한국어 |
| 💬 Chat | Toca al gato → escribe o pulsa 🎤 para hablar (Enter para enviar); respuestas en streaming de DeepSeek, recuerda tu nombre y preferencias, y puede «recuérdame beber agua en 10 minutos» |
| 🧹 Tareas | «Ordenar escritorio» primero analiza, muestra una vista previa, solo actúa si confirmas y se puede deshacer; también «abre Safari», «qué hora es», «cuenta un chiste» |
| 😴 **Descanso** | **Pulsa 😴 y el gato deja de girar, se tumba y bosteza para dormir** (clip de bostezo + velo nocturno + zzz flotantes); pulsa otra vez o toca al gato para despertarlo |
| ✨ **Menú de acciones** | **Pulsa ✨ para abrir un menú que nombra lo que Xuetuan sabe hacer: saludar / ver el paisaje / relajarse / bostezar y dormir — eliges y se reproduce** |
| 🖱️ Detalles | Alternar clic transparente (no bloquea los iconos); un pequeño indicador mientras piensa, oculto durante el descanso; icono del gato en la barra de menús como respaldo |

### 🆕 Novedades

1. **😴 Descanso ahora significa quedarse realmente quieto** — al pulsarlo, la escena principal se pausa (ya no gira) y el gato **bosteza una sola vez y se queda congelado, dormido e inmóvil**. Antes el bostezo se reproducía en bucle, así que en rigor seguía moviéndose; ahora es «una vez + congelar el último fotograma», con velo nocturno y zzz flotantes.
2. **✨ pasó de «aleatorio» a menú de acciones** — antes lanzaba una acción al azar y no se sabía para qué servía (justo por eso el botón resultaba ilegible). Ahora abre botones **con nombre**, traducidos a los 7 idiomas.
3. **Los botones 😴 / ✨ recuperaron su estilo** — no tenían CSS y usaban el aspecto por defecto del navegador, es decir dos cuadrados irreconocibles. Ahora son como 🎤🔊 y laten suavemente durante el descanso.
4. **La demo ya tiene sonido** — 16 segundos, saludo en siete idiomas (zh / en / ja / ko / es / pt / fr), cada uno con una voz del sistema, sobre un fondo de viento invernal; los últimos 3 segundos muestran «bostezo → dormido».
5. **Francés añadido al README** — ya están las 7 lenguas.
6. **Mismo interruptor en la barra de menús** — «Que Xuetuan duerma», sincronizado y recordado tras reiniciar.

### 🚀 Ejecutar

```bash
pip3 install pyobjc
python3 desktop_pet.py        # o doble clic en 启动桌面挂件.command
```

> Solo macOS. Carga `桌面伴侣-雪团-壁纸.html` por defecto (generado desde `wallpaper_template.html` por `build_wallpaper.py`).

---

## Português

Xuetuan é um companheiro de desktop em forma de gato original para macOS. Sem Electron: apenas pyobjc nativo e um WKWebView. Fica quietinho na camada da área de trabalho; toque nele para conversar, trocar a estação, organizar a mesa ou simplesmente deixá-lo tirar uma soneca.

### ✨ Destaques

| Área | O que faz |
| --- | --- |
| 🎬 Cenário | Companheiro em tela cheia estilo papel de parede; quatro estações (cerejeira na primavera / verde no verão / bordo no outono / neve no inverno). O inverno é um vídeo de neve; os outros, imagem + partículas |
| 🌐 Idiomas | Interface, voz, reconhecimento e respostas do modelo mudam juntos em 7 idiomas: 中文, English, Español, Français, Português, 日本語, 한국어 |
| 💬 Conversa | Clique no gato → digite ou toque em 🎤 para falar (Enter para enviar); respostas em streaming do DeepSeek, lembra seu nome e preferências, e pode «me lembre de beber água em 10 minutos» |
| 🧹 Tarefas | «Organizar a mesa» primeiro escaneia, mostra uma prévia, só age após confirmar e pode desfazer; também «abra o Safari», «que horas são», «conte uma piada» |
| 😴 **Descanso** | **Toque em 😴 e o gato para de girar, deita e boceja para dormir** (clipe de bocejo + véu noturno + zzz flutuantes); toque de novo ou no gato para acordar |
| ✨ **Menu de ações** | **Toque em ✨ para abrir um menu que diz o que a Xuetuan sabe fazer: dar oi / ver a paisagem / relaxar / bocejar e dormir — você escolhe e ela faz** |
| 🖱️ Detalhes | Alternar clique transparente (não bloqueia ícones); um pequeno indicador enquanto pensa, oculto durante o descanso; ícone do gato na barra de menus como alternativa |

### 🆕 Novidades

1. **😴 Descanso agora é ficar realmente parado** — ao tocar, a cena principal pausa (não gira mais) e o gato **boceja uma única vez e congela, dormindo e completamente imóvel**. Antes o bocejo ficava em loop, ou seja, ele ainda se mexia; agora é «toca uma vez + congela no último quadro», com véu noturno e zzz flutuantes.
2. **✨ deixou de ser «aleatório» e virou menu de ações** — antes disparava uma ação ao acaso e não dava para saber para que servia (foi por isso que o botão ficou ilegível). Agora abre botões **com nome**, traduzidos nos 7 idiomas.
3. **Os botões 😴 / ✨ recuperaram o estilo** — estavam sem CSS e usavam a aparência padrão do navegador, ou seja, dois quadrados irreconhecíveis. Agora são iguais a 🎤🔊 e pulsam devagar durante o descanso.
4. **A demo agora tem som** — 16 segundos, cumprimento em sete idiomas (zh / en / ja / ko / es / pt / fr), cada um com uma voz do sistema, sobre um fundo de vento de inverno; os últimos 3 segundos mostram «bocejo → sono».
5. **Francês adicionado ao README** — agora são 7 idiomas documentados.
6. **Mesmo interruptor na barra de menus** — «Xuetuan tirar uma soneca», sincronizado e lembrado após reiniciar.

### 🚀 Executar

```bash
pip3 install pyobjc
python3 desktop_pet.py        # ou clique duas vezes em 启动桌面挂件.command
```

> Somente macOS. Carrega `桌面伴侣-雪团-壁纸.html` por padrão (gerado de `wallpaper_template.html` por `build_wallpaper.py`).

---

## Français

Xuetuan est un compagnon de bureau en forme de chat original pour macOS. Pas d'Electron : uniquement pyobjc natif et un seul WKWebView. Il reste tranquille sur la couche du bureau ; touchez-le pour discuter, changer de saison, ranger votre bureau, ou simplement le laisser faire une sieste.

### ✨ Points forts

| Domaine | Ce qu'il fait |
| --- | --- |
| 🎬 Scène | Compagnon plein écran façon fond d'écran ; quatre saisons (cerisiers au printemps / vert en été / érable en automne / neige en hiver). L'hiver est une vidéo de neige, les autres sont des images + particules |
| 🌐 Langues | Interface, voix, reconnaissance vocale et réponses du modèle basculent ensemble dans 7 langues : 中文, English, Español, Français, Português, 日本語, 한국어 |
| 💬 Conversation | Touchez le chat → tapez, ou appuyez sur 🎤 pour parler (Entrée pour envoyer) ; réponses en streaming depuis DeepSeek, il retient votre nom et vos préférences, et sait « rappelle-moi de boire de l'eau dans 10 minutes » |
| 🧹 Corvées | « Ranger le bureau » analyse d'abord, affiche un aperçu, n'agit qu'après confirmation et peut être annulé ; aussi « ouvre Safari », « quelle heure est-il », « raconte une blague » |
| 😴 **Repos** | **Appuyez sur 😴 : le chat arrête de tourner en rond, s'allonge, bâille puis s'endort — puis il se fige et ne bouge plus du tout** (clip de bâillement + voile nocturne + zzz flottants). Appuyez à nouveau, ou touchez le chat, pour le réveiller |
| ✨ **Menu d'actions** | **Appuyez sur ✨ pour ouvrir un menu qui nomme ce que Xuetuan sait faire : dire bonjour / voir le paysage / se détendre / bâiller et dormir** |
| 🖱️ Détails | Bascule de clic traversant (ne bloque pas les icônes du bureau) ; un petit indicateur pendant qu'il réfléchit, masqué pendant le repos ; une icône de chat dans la barre de menus comme solution de repli |

### 🆕 Nouveautés

1. **😴 Le repos, c'est vraiment l'immobilité** — appuyer met d'abord la scène principale en pause (fini les tours), puis le chat **bâille une seule fois et se fige, endormi et parfaitement immobile**. Avant, le bâillement tournait en boucle, donc il bougeait encore ; désormais c'est « une lecture + arrêt sur la dernière image », avec voile nocturne et zzz flottants.
2. **✨ passe d'« aléatoire » à un menu d'actions** — il déclenchait une action au hasard, sans qu'on sache à quoi il servait (c'est précisément pourquoi le bouton était illisible). Il ouvre maintenant des boutons **nommés**, traduits dans les 7 langues.
3. **Les boutons 😴 / ✨ ont retrouvé leur style** — ils n'avaient aucune règle CSS et prenaient l'apparence par défaut du navigateur, soit deux carrés méconnaissables. Ils ressemblent désormais à 🎤🔊 et pulsent doucement pendant le repos.
4. **La vidéo de démo a du son** — 16 secondes, bonjour dans sept langues (zh / en / ja / ko / es / pt / fr), chacune lue par une voix système correspondante, sur un fond de vent d'hiver ; les 3 dernières secondes montrent « bâillement → sommeil ».
5. **Le français ajouté au README** — les 7 langues sont maintenant documentées.
6. **Même interrupteur dans la barre de menus** — « Faire faire la sieste à Xuetuan », synchronisé avec le bouton et mémorisé après redémarrage.

### 🚀 Lancer

```bash
pip3 install pyobjc
python3 desktop_pet.py        # ou double-clic sur 启动桌面挂件.command
```

> macOS uniquement. Charge `桌面伴侣-雪团-壁纸.html` par défaut (généré depuis `wallpaper_template.html` par `build_wallpaper.py`).

---

## 📁 文件结构 / Project layout

```
desktop_pet.py                 # 主程序（原生窗口、消息桥、i18n、语音、LLM、动作/休息）
wallpaper_template.html        # 页面模板（场景/宠物双模式、动作层、休息层）
build_wallpaper.py             # 把模板 + 资源打包成自包含 HTML
启动桌面挂件.command            # 双击启动
assets/
  scene_loop.mp4               # 冬季场景视频（猫长在里面）
  act_hello / act_scenery / act_idle / act_yawn.mp4   # 额外动作 / 打哈欠
  season_spring / summer / autumn / winter .jpg       # 四季背景
xuetuan_demo.mp4 / .gif        # 16 秒七语言演示（视频含系统音色旁白）
```

## 🛠 技术栈 / Tech

- macOS 原生：`pyobjc`（AppKit / WebKit / Quartz / AVFoundation）
- 界面：单文件 HTML + 原生 JS，`WKWebView` 双窗口（桌面层场景窗 + 可点宠物窗）
- 对话：DeepSeek 流式 API
- 语音：`say`（TTS）+ SFSpeechRecognizer（STT）
- 视频 / GIF：ffmpeg

## 📄 License

个人作品，供学习与自用。样式与素材（含 AI 生成画面）请勿直接商用。 / Personal project for learning and personal use. Please don't resell the art assets (including AI-generated visuals).

<div align="center">

🐱 **雪团 · 陪你四季** · Made with pyobjc & a lot of cat hair.

</div>
