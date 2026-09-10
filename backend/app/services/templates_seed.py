"""内置风格模板 — 提示词与风格描述统一中文。

分类约定（category[0] 为主分类，用于首页筛选）：
电影感 / 真人感 / 写实感 / 科普 / 儿童 / 国风 / 科幻 / 动漫 / 商业 / 复古 / 纪录片 / 奇幻 / 图文 / 悬疑 / 开源
真人感、写实感模板须在 seedream_config 设 photoreal: true。

一致性（seedream_config.consistency_mode）：
- character：人物+画风锁定，镜间图生图链式参考（叙事默认）
- style：仅画风气质，不锁人物、不链式参考
- diverse：按内容动态规划独立场景（开源/产品演示），禁止镜间雷同
未设置时回退 seedance/seedream 的 character_consistency。

成片方式（是否生成 AI 视频）由用户在风格配置页选择，不再由模板锁定。
模板 default_ratio 仅作画幅默认建议。
"""

TEMPLATES: list[dict] = [
    {
        "id": "opensource_showcase",
        "name": "开源项目展示",
        "description": "按项目内容动态规划：人物操作系统界面与真实使用场景，适合开源工具与平台介绍。",
        "category": ["开源", "图文", "商业"],
        "preview_cover": "/static/templates/covers/opensource_showcase.png",
        "style_prefix": (
            "高品质产品演示静帧：人物在真实工位前操作软件/文档站/工作台，"
            "手部点击与屏幕界面清晰，排版克制、信息层级清楚，"
            "材质与配色由内容决定（浅色SaaS、纸感文档、深色IDE、终端均可），"
            "电影级产品演示质感，干净留白便于叠字，非任务清单界面"
        ),
        "negative_prompt": (
            "任务列表，todolist，勾选框，看板卡片堆叠，"
            "霓虹蓝，赛博朋克蓝光，全屏蓝紫渐变，发光网格地板，科幻HUD堆叠，"
            "卡通夸张，动漫美少女，手绘潦草，画面乱码文字，字幕水印，logo乱码，模糊，"
            "空界面无操作者，纯抽象色块"
        ),
        "default_ratio": "9:16",
        "shot_duration_min": 5,
        "shot_duration_max": 12,
        "llm_system_addon": (
            "这是开源/产品展示片。先【分析】用户文案：项目类型、核心能力、典型用户与使用路径，"
            "再规划分镜与视觉，不要套固定蓝光大屏。"
            "【画面硬性要求】每镜必须出现「人在操作系统」："
            "操作员坐在工位前使用电脑/笔记本/平板，点击界面、填写配置、查看看板、"
            "演示核心流程、部署发布或阅读文档；可辅以屏幕特写，但禁止整片只有空 UI 无人。"
            "【逐段】每镜输出 segments：visual 与 narration 交替；单段 3-12 秒，镜合计适配口播。"
            "【视觉】色板与界面气质跟内容走（浅色后台、IDE、文档站、终端等），禁止默认霓虹蓝。"
            "【分镜】每镜对应不同能力或操作场景，构图必须明显不同，禁止待办清单/人物剧情戏。"
            "title=模块短名（2-8字），subtitle=能力卖点（10-22字），text=口播；"
            "img_prompt 写清人物姿态、面前界面类型、操作动作与主色。"
        ),
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "consistency_mode": "diverse",
            "character_prompt": (
                "产品演示操作员：侧脸或过肩视角，坐在工位前操作笔记本电脑或双屏，"
                "商务休闲着装，手部与屏幕为视觉重点，五官不必抢戏，全片气质统一"
            ),
            "extra_prompt": (
                "主体为人操作系统界面，手部点击可读，禁止霓虹蓝赛博大屏；"
                "顶部与底部留白便于叠大字，画面内不要出现任何文字；"
                "本镜布局与操作动作须与其他镜头明显不同"
            ),
        },
        "seedance_config": {
            "motion_bias": "手部轻微点击与屏幕内容切换，缓慢推近工位",
            "character_consistency": False,
            "generate_audio": True,
        },
        "audio_config": {"voice_preset": "urban_editorial", "bgm_mood": "轻快专业"},
        "subtitle_config": {
            "font": "SourceHanSans",
            "position": "split",
            "title_scale": 1.7,
            "sub_scale": 1.55,
            "caption_scale": 1.3,
        },
        "sort_order": 1,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "opensource_live_work",
        "name": "真人工作场景",
        "description": "真人写实工位操作：侧脸/过肩操作系统，适合开源工具与产品工作流科普。",
        "category": ["开源", "真人感", "写实感"],
        "preview_cover": "/static/templates/covers/opensource_live_work.png",
        "style_prefix": (
            "真人写实摄影，真实办公室工位，侧脸或过肩视角操作笔记本电脑/双屏，"
            "手部点击与屏幕界面清晰，自然窗光与显示器补光，商务休闲着装，"
            "皮肤与材质真实，非卡通非动漫，干净留白便于叠字"
        ),
        "negative_prompt": (
            "卡通，动漫，赛璐璐，二次元，美颜过度磨皮，CGI假人，"
            "霓虹蓝赛博大屏，任务清单堆叠，空界面无操作者，画面文字水印，模糊"
        ),
        "default_ratio": "16:9",
        "shot_duration_min": 6,
        "shot_duration_max": 12,
        "llm_system_addon": (
            "这是开源「真人工作场景」片。先分析项目能力与使用路径，再按内容拆多镜短镜。"
            "【硬性】每镜必须出现真人在工位操作系统（侧脸/过肩/手部焦点，少正脸特写）。"
            "【逐段】每镜必须输出 segments 数组：交替 visual（景别+动作+界面类型）与 narration（口播）；"
            "单段 duration 3-12 秒，镜内合计不超过 12 秒；旁白按约 5 字/秒估时长，禁止拖腔注水。"
            "【节拍】痛点工位→接入配置→核心工作台→流程结果→协作/部署；构图与操作动作禁止雷同。"
            "title=模块短名，subtitle=卖点句，bgm 全片统一为轻快专业。"
        ),
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "photoreal": True,
            "consistency_mode": "diverse",
            "character_prompt": (
                "写实产品演示操作员：侧脸或过肩，坐在工位前操作笔记本或双屏，"
                "商务休闲着装，手部与屏幕为视觉重点，五官不抢戏，气质全片统一"
            ),
            "extra_prompt": (
                "真人写实工位，手部点击可读，界面类型随内容变化；"
                "禁止正脸大特写与霓虹赛博大屏；画面内不要出现文字"
            ),
        },
        "seedance_config": {
            "motion_bias": "手部轻微点击与屏幕内容切换，缓慢推近工位",
            "character_consistency": False,
            "generate_audio": True,
        },
        "audio_config": {"voice_preset": "urban_editorial", "bgm_mood": "轻快专业"},
        "subtitle_config": {
            "font": "SourceHanSans",
            "position": "split",
            "title_scale": 1.6,
            "sub_scale": 1.45,
            "caption_scale": 1.25,
        },
        "sort_order": 2,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "live_street_interview",
        "name": "真人街访口播",
        "description": "街头/通勤场景的真人出镜口播感，适合观点、体验与轻访谈科普。",
        "category": ["真人感", "纪录片"],
        "preview_cover": "/static/templates/covers/live_street_interview.png",
        "style_prefix": (
            "真人纪实街访摄影，自然光与轻微手持感，城市街道或通勤场景，"
            "真实皮肤与环境噪音感克制，非棚拍浓妆，非卡通非动漫"
        ),
        "negative_prompt": "卡通，动漫，赛璐璐，二次元，棚拍浓妆，CGI假人，霓虹赛博，画面文字水印",
        "default_ratio": "9:16",
        "shot_duration_min": 5,
        "shot_duration_max": 12,
        "llm_system_addon": (
            "真人街访/口播节奏。每镜输出 segments：建立环境 visual → narration 口播 → 反应/细节 visual。"
            "人物外形全片一致；少正脸极端特写。title 短、subtitle 观点句。"
        ),
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "photoreal": True,
            "character_prompt": "真人街访主角：年龄气质、发型服装日常感固定，自然表情，全片同一人",
            "extra_prompt": "自然光街景或通勤场景，竖屏主体清晰，顶部可留白叠字",
        },
        "seedance_config": {
            "motion_bias": "轻微手持感，缓慢推近",
            "character_consistency": True,
            "generate_audio": True,
        },
        "audio_config": {"voice_preset": "warm_storyteller", "bgm_mood": "温暖人文"},
        "subtitle_config": {"font": "SourceHanSans", "position": "top", "caption_scale": 1.3},
        "sort_order": 3,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "live_product_desk",
        "name": "真人桌面演示",
        "description": "桌面俯拍/斜俯写实：真人双手演示产品或笔记本流程，适合工具评测与教程。",
        "category": ["真人感", "写实感", "商业"],
        "preview_cover": "/static/templates/covers/live_product_desk.png",
        "style_prefix": (
            "真人桌面产品演示摄影，斜俯或过肩，木质/浅色桌面，笔记本与手部清晰，"
            "柔和棚灯或窗光，材质真实，非卡通非插画"
        ),
        "negative_prompt": "卡通，动漫，赛璐璐，二次元，空桌无手，霓虹赛博，画面乱码文字水印",
        "default_ratio": "16:9",
        "shot_duration_min": 5,
        "shot_duration_max": 12,
        "llm_system_addon": (
            "桌面演示片。每镜 segments 必须含手部操作 visual + narration；"
            "景别在全桌建立、手部特写、屏幕内容之间切换，禁止各镜雷同。"
        ),
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "photoreal": True,
            "consistency_mode": "diverse",
            "character_prompt": "写实双手与小臂为主，可露侧脸；着装简洁，全片气质统一",
            "extra_prompt": "桌面斜俯，手部与产品/屏幕清晰，画面内无文字",
        },
        "seedance_config": {
            "motion_bias": "手部点击滑动，轻微推近屏幕",
            "character_consistency": False,
            "generate_audio": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "冷静纪实"},
        "subtitle_config": {
            "font": "SourceHanSans",
            "position": "split",
            "title_scale": 1.5,
            "sub_scale": 1.4,
            "caption_scale": 1.25,
        },
        "sort_order": 4,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "portrait_story",
        "name": "竖屏图文故事",
        "description": "竖屏插画叙事，电影感构图，适合历史人文短片。",
        "category": ["图文", "电影感", "故事"],
        "preview_cover": "/static/templates/covers/portrait_story.png",
        "style_prefix": "统一二维概念插画，细腻光影与电影感构图，非写实摄影、非日系赛璐璐动漫，竖屏主体偏中下，顶部留白便于叠字，画面干净无文字",
        "negative_prompt": "写实照片，真人，真实人脸，摄影棚，电影真人剧照，日系动漫赛璐璐，画面文字，字幕，水印，标题字，logo，模糊",
        "default_ratio": "9:16",
        "shot_duration_min": 4,
        "shot_duration_max": 12,
        "llm_system_addon": "按故事节拍拆镜：起承转合。每镜 title 短标题、subtitle 叠字副标题、text 为可朗读旁白。画面必须全片统一插画风与人物外形，禁止某镜突然变成真人照片或另一套动漫风。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "character_prompt": "故事主角外形固定：年龄感、发型发色、服装配色与辨识物全片一致，细腻插画五官，非真人照片",
            "extra_prompt": "竖屏构图，主体偏中下，顶部约1/4留白，电影感光影，画面内无文字",
        },
        "seedance_config": {
            "motion_bias": "缓慢推近或轻拉远",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "叙事氛围"},
        "subtitle_config": {
            "font": "SourceHanSans",
            "position": "top",
            "title_scale": 1.4,
            "sub_scale": 1.35,
            "caption_scale": 1.3,
        },
        "sort_order": 5,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "live_cinematic",
        "name": "真人电影感",
        "description": "真人实拍电影质感，戏剧光影与浅景深，适合叙事短片。",
        "category": ["电影感", "真人感"],
        "preview_cover": "/static/templates/covers/live_cinematic.png",
        "style_prefix": "真人电影感摄影，电影级打光与浅景深，胶片质感与轻微颗粒，青橙调色，写实皮肤与真实材质，宽银幕构图，非卡通非动漫",
        "negative_prompt": "卡通，动漫，赛璐璐，二次元，扁平插画，剪纸，像素，夸张五官，塑料皮肤，水印，画面文字",
        "default_ratio": "16:9",
        "shot_duration_min": 4,
        "shot_duration_max": 12,
        "llm_system_addon": "按真人电影分镜：建立镜头→中景→特写。全片必须同一真人写实画风与同一演员外形，禁止某镜变成卡通。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.75,
            "photoreal": True,
            "character_prompt": "真人演员外形固定：年龄、发型发色、面部特征、服装全片一致，写实皮肤质感",
            "extra_prompt": "电影打光、浅景深、胶片颗粒，真实场景材质",
        },
        "seedance_config": {
            "motion_bias": "电影感推轨或轻微横移，自然运动模糊",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "电影氛围"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom", "caption_scale": 1.3},
        "sort_order": 6,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "live_person",
        "name": "真人感叙事",
        "description": "生活化真人出镜感，适合人物故事、口播与纪实短片。",
        "category": ["真人感", "故事"],
        "preview_cover": "/static/templates/covers/live_person.png",
        "style_prefix": "真人感生活摄影，自然光与柔和环境光，真实人物五官与皮肤质感，纪实构图，非棚拍浓妆，非卡通非动漫",
        "negative_prompt": "卡通，动漫，赛璐璐，二次元，美颜过度磨皮，CGI假人，扁平插画，水印，画面文字",
        "default_ratio": "9:16",
        "shot_duration_min": 3,
        "shot_duration_max": 12,
        "llm_system_addon": "人物叙事节奏，旁白口语化。全片统一真人写实画风与同一人物外形。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "photoreal": True,
            "character_prompt": "真人出镜主角：年龄气质、发型发色、服装日常感固定，自然表情，全片同一人",
            "extra_prompt": "自然光、生活场景、竖屏主体清晰，顶部可留白叠字",
        },
        "seedance_config": {
            "motion_bias": "轻微手持感，缓慢推近",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "warm_storyteller", "bgm_mood": "温暖人文"},
        "subtitle_config": {"font": "SourceHanSans", "position": "top"},
        "sort_order": 7,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "photo_realism",
        "name": "写实摄影",
        "description": "照片级写实质感，适合产品、风光与纪实科普。",
        "category": ["写实感", "摄影"],
        "preview_cover": "/static/templates/covers/photo_realism.png",
        "style_prefix": "照片级写实摄影，清晰细节与真实材质，自然色彩，高动态范围，微距或风光皆可，非卡通非插画非动漫",
        "negative_prompt": "卡通，动漫，赛璐璐，扁平插画，油画笔触，剪纸，像素，过度HDR伪色，水印，画面文字",
        "default_ratio": "16:9",
        "shot_duration_min": 3,
        "shot_duration_max": 12,
        "llm_system_addon": "写实镜头语言：全景建立→细节特写。若有人物须外形全片一致；可无人物纯场景。禁止卡通化。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "photoreal": True,
            "character_prompt": "若出现人物：写实五官与发型服装固定；若无人物则专注真实场景与材质",
            "extra_prompt": "照片级细节、真实材质、自然色彩，清晰主体",
        },
        "seedance_config": {
            "motion_bias": "缓慢推近或轻微横移，真实空间感",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "冷静纪实"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 7,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "film_cinematic",
        "name": "电影感胶片",
        "description": "宽银幕胶片质感与戏剧光影，适合叙事短片与氛围故事。",
        "category": ["电影感", "胶片"],
        "preview_cover": "/static/templates/covers/film_cinematic.png",
        "style_prefix": "电影感概念插画，宽银幕构图，胶片颗粒与轻微暗角，戏剧光影（侧光/逆光），青橙调色倾向，浅景深氛围，非写实摄影、非赛璐璐动漫",
        "negative_prompt": "写实照片，真人，真实人脸，日系动漫，赛璐璐，扁平贴纸风，过曝，水印，画面文字，卡通简笔画",
        "default_ratio": "16:9",
        "shot_duration_min": 4,
        "shot_duration_max": 12,
        "llm_system_addon": "按电影分镜节奏：建立镜头→特写→反应镜头。台词克制，留白给画面。全片统一胶片插画风与角色外形。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "character_prompt": "电影感插画主角，明确年龄与发型发色，服装轮廓与辨识物固定，面部细节适中非照片，全片同一人设",
            "extra_prompt": "胶片颗粒、暗角、戏剧光影，青橙氛围，宽银幕主体明确",
        },
        "seedance_config": {
            "motion_bias": "缓慢推轨或轻微横移，电影感运镜，避免抖动",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "电影氛围"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 8,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "noir_thriller",
        "name": "黑色悬疑",
        "description": "高对比光影与冷调氛围，适合悬疑、案件与暗夜叙事。",
        "category": ["悬疑", "电影感"],
        "preview_cover": "/static/templates/covers/noir_thriller.png",
        "style_prefix": "黑色电影概念插画，高对比明暗交界，冷青灰与少量暖光点缀，雨夜或室内台灯氛围，剪影与侧脸，非写实摄影",
        "negative_prompt": "明亮粉彩，儿童绘本，日系美少女，写实照片，真人，血腥特写，水印，画面文字",
        "default_ratio": "16:9",
        "shot_duration_min": 4,
        "shot_duration_max": 12,
        "llm_system_addon": "悬疑节奏：线索→反转→压迫。台词短句，画面多用阴影与构图张力。全片统一黑色电影插画风。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "character_prompt": "Noir 风插画角色，轮廓清晰，大衣或标志性剪影，面部少光，外形全片一致",
            "extra_prompt": "高对比阴影、冷调、雨夜或台灯，强构图张力",
        },
        "seedance_config": {
            "motion_bias": "极慢推近，烟雾或雨丝轻微飘动",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "悬疑低沉"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 9,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "vox_papercut",
        "name": "Vox剪纸科普",
        "description": "低饱和扁平剪纸，以人物操作电脑/系统界面为主画面，适合硬核科普与产品讲解。",
        "category": ["科普", "剪纸"],
        "preview_cover": "/static/templates/covers/vox_papercut.png",
        "style_prefix": (
            "Vox剪纸扁平插画，层叠剪纸边缘，低饱和，干净剪影，科普解说片气质；"
            "画面以人物操作电脑或业务系统为主：工位前操作、手指点击界面、多屏监控、"
            "配置参数、流程演示，屏幕与手部动作清晰，信息图表为辅"
        ),
        "negative_prompt": (
            "写实照片，真人照片级皮肤，三维写实渲染，日系动漫，模糊，噪点，水印，"
            "画面乱码文字，空镜风景无人物无界面，纯抽象色块无操作场景"
        ),
        "default_ratio": "16:9",
        "shot_duration_min": 4,
        "shot_duration_max": 15,
        "llm_system_addon": (
            "按科普讲解节奏拆镜，台词口语化、信息密度适中。"
            "【画面硬性要求】每镜必须出现「人在操作系统」："
            "剪纸人物坐在工位/控制台前操作电脑或平板，点击鼠标键盘、切换菜单、"
            "查看仪表盘、填写表单、对比前后状态、演示关键流程等；"
            "可辅以屏幕特写或架构示意图，但禁止整片只有空概念图、无操作者。"
            "title/subtitle 概括本镜知识点；img_prompt 写清人物姿态、面前屏幕内容类型与操作动作。"
            "全片同一剪纸画风与同一操作员外形。"
        ),
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "character_prompt": (
                "固定剪纸操作员：简洁人形剪影、低细节面部、工装或休闲色块服装固定，"
                "常坐工位前操作笔记本电脑或双屏控制台，发型与配色全片一致"
            ),
            "extra_prompt": (
                "主体为人操作电脑/系统界面，屏幕区块与点击手势可读，"
                "层叠纸片边缘清晰，低饱和，单镜一个视觉焦点，避免写实皮肤"
            ),
        },
        "seedance_config": {
            "motion_bias": "手部轻微点击与光标移动感，屏幕内容轻切换，缓慢推近工位",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "好奇纪录片"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 10,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "docu_warm",
        "name": "温暖纪实",
        "description": "纪实插画气质与暖色调，适合人物故事与人文纪录短片。",
        "category": ["纪录片", "电影感"],
        "preview_cover": "/static/templates/covers/docu_warm.png",
        "style_prefix": "温暖纪实概念插画，自然光感，柔和暖棕与米白，生活场景细节，纪录片构图，非写实照片、非动漫赛璐璐",
        "negative_prompt": "赛博霓虹，日系美少女，血腥，夸张卡通，写实照片，真人，水印，画面文字",
        "default_ratio": "16:9",
        "shot_duration_min": 4,
        "shot_duration_max": 14,
        "llm_system_addon": "人文纪录节奏：观察→细节→情感落点。旁白平和真诚。全片统一温暖纪实插画风与人物外形。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.68,
            "character_prompt": "纪实插画人物，生活化发型服装，亲切五官，年龄感明确，全片同一人设",
            "extra_prompt": "暖色自然光，生活场景，纪录片式构图，柔和颗粒",
        },
        "seedance_config": {
            "motion_bias": "手持感极轻晃动或缓慢横移，纪实运镜",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "warm_storyteller", "bgm_mood": "温暖人文"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 12,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "kids_flat",
        "name": "儿童绘本扁平",
        "description": "柔和配色与圆润造型，适合儿童科普与故事。",
        "category": ["儿童", "绘本"],
        "preview_cover": "/static/templates/covers/kids_flat.png",
        "style_prefix": "儿童绘本扁平插画，柔和粉彩，圆润造型，友好角色，简洁背景",
        "negative_prompt": "恐怖，阴暗，写实照片，复杂纹理，血腥",
        "default_ratio": "16:9",
        "shot_duration_min": 3,
        "shot_duration_max": 12,
        "llm_system_addon": "用孩子听得懂的短句，每镜突出一个可爱视觉元素，节奏轻快。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.65,
            "character_prompt": "圆润可爱卡通角色，大眼睛简化五官，柔和配色服装，友好表情，全片同一角色外形",
            "extra_prompt": "粉彩柔光，背景简洁，造型圆润，适合儿童观看",
        },
        "seedance_config": {
            "motion_bias": "轻微弹跳感，柔和镜头漂移",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "warm_storyteller", "bgm_mood": "俏皮轻快"},
        "subtitle_config": {"font": "RoundedSans", "position": "bottom"},
        "sort_order": 20,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "soft_anime",
        "name": "柔光动漫",
        "description": "日系柔光赛璐璐，适合青春故事与情感短片。",
        "category": ["动漫", "故事"],
        "preview_cover": "/static/templates/covers/soft_anime.png",
        "style_prefix": "日系柔光赛璐璐动漫，干净线稿，柔和渐变天空，大眼睛精致五官，统一角色设定，非写实摄影、非水墨、非剪纸",
        "negative_prompt": "写实照片，真人，真实人脸，水墨，剪纸，像素风，血腥恐怖，水印，画面文字，三头身Q版混用",
        "default_ratio": "16:9",
        "shot_duration_min": 3,
        "shot_duration_max": 12,
        "llm_system_addon": "青春动漫叙事：情绪镜+对话镜交替。全片必须同一赛璐璐画风与角色外形，禁止某镜变真人。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "character_prompt": "日系动漫主角，发型发色瞳色固定，校服或常服配色固定，赛璐璐五官，全片同一人设",
            "extra_prompt": "柔光、干净线稿、柔和天空，统一赛璐璐上色",
        },
        "seedance_config": {
            "motion_bias": "轻微发丝与衣袂飘动，缓慢推近",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "warm_storyteller", "bgm_mood": "青春轻音乐"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 22,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "chalk_whiteboard",
        "name": "粉笔白板手绘",
        "description": "黑板粉笔讲解风，突出人物操作系统/画流程图的课堂演示。",
        "category": ["科普", "手绘"],
        "preview_cover": "/static/templates/covers/chalk_whiteboard.png",
        "style_prefix": (
            "黑板粉笔与白板手绘讲解风，粉笔笔触，示意图箭头；"
            "画面常含简笔人物在白板或电脑前操作系统、画流程、指点界面"
        ),
        "negative_prompt": "写实照片，光滑三维，杂乱界面，空教室无人物",
        "default_ratio": "16:9",
        "shot_duration_min": 4,
        "shot_duration_max": 15,
        "llm_system_addon": (
            "偏讲解结构：定义→例子→对比。"
            "每镜尽量出现简笔人物操作系统或在白板上演示系统流程"
            "（指点屏幕、画模块箭头、对比操作前后），避免只有抽象符号没有操作者。"
        ),
        "seedream_config": {
            "ref_images": [],
            "strength": 0.6,
            "character_prompt": (
                "粉笔简笔讲解者/操作员，线条简洁特征固定，"
                "常站在白板前或坐在电脑前指点界面"
            ),
            "extra_prompt": "黑板/白板底，人物操作系统或画流程图，箭头清晰，教学感构图",
        },
        "seedance_config": {
            "motion_bias": "手部指点与线条逐步显现，镜头基本固定或轻推",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "teacher_clear", "bgm_mood": "专注氛围"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 30,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "cyber_neon",
        "name": "赛博霓虹",
        "description": "霓虹夜城与未来感，适合科技、都市与科幻话题。",
        "category": ["科幻", "赛博"],
        "preview_cover": "/static/templates/covers/cyber_neon.png",
        "style_prefix": "赛博朋克概念插画，霓虹粉青对比，雨夜反光街道，未来都市剪影，高对比夜景，非写实摄影、非儿童绘本",
        "negative_prompt": "日光沙滩，田园水彩，儿童粉彩，写实照片，真人，水墨留白，水印，画面文字",
        "default_ratio": "16:9",
        "shot_duration_min": 3,
        "shot_duration_max": 12,
        "llm_system_addon": "科技/都市节奏偏快，每镜一个强视觉符号（霓虹、屏幕、雨夜）。全片统一赛博插画风。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "character_prompt": "赛博风插画角色，外套剪裁与发色固定，霓虹边缘光，面部非照片，全片同一人设",
            "extra_prompt": "霓虹粉青、雨夜反光、未来都市，强对比夜景",
        },
        "seedance_config": {
            "motion_bias": "霓虹闪烁，雨丝下落，缓慢穿梭运镜",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "urban_editorial", "bgm_mood": "赛博电子"},
        "subtitle_config": {"font": "DisplaySans", "position": "bottom"},
        "sort_order": 35,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "epic_fantasy",
        "name": "奇幻史诗",
        "description": "宏大场景与奇幻光影，适合神话、冒险与世界观短片。",
        "category": ["奇幻", "电影感"],
        "preview_cover": "/static/templates/covers/epic_fantasy.png",
        "style_prefix": "奇幻史诗概念插画，宏大远景与英雄中景，暮光与神性光束，岩石城堡与云海，戏剧构图，非写实摄影、非现代都市",
        "negative_prompt": "现代城市，手机界面，写实照片，真人，儿童简笔画，赛博霓虹，水印，画面文字",
        "default_ratio": "16:9",
        "shot_duration_min": 4,
        "shot_duration_max": 14,
        "llm_system_addon": "史诗叙事：远景建立世界观→人物登场→冲突高潮。台词可略庄重。全片统一奇幻插画风。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.72,
            "character_prompt": "奇幻主角外形固定：盔甲或斗篷轮廓、发色、武器辨识物全片一致，插画五官非照片",
            "extra_prompt": "宏大场景、暮光神性光束、戏剧构图，史诗氛围",
        },
        "seedance_config": {
            "motion_bias": "缓慢升降镜头，云雾与旗帜飘动",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "narrator_calm", "bgm_mood": "史诗管弦"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 38,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "magazine_collage",
        "name": "杂志拼贴",
        "description": "剪报拼贴与印刷纹理，适合文化话题与品牌故事。",
        "category": ["商业", "拼贴"],
        "preview_cover": "/static/templates/covers/magazine_collage.png",
        "style_prefix": "杂志纸质拼贴，撕边，网纹印刷质感，层叠剪贴，大胆平面构图",
        "negative_prompt": "纯净矢量，写实皮肤，脏污发灰的色彩",
        "default_ratio": "9:16",
        "shot_duration_min": 4,
        "shot_duration_max": 12,
        "llm_system_addon": "视觉冲击优先，每镜一个强构图，文案短而有力。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.75,
            "character_prompt": "杂志剪贴人像剪影或印刷半调人物，外形与配色全片统一",
            "extra_prompt": "撕边纸质、网纹印刷、大胆色块，竖屏强构图",
        },
        "seedance_config": {
            "motion_bias": "图层轻微滑动旋转，纸张沙沙感",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "urban_editorial", "bgm_mood": "时髦轻电子"},
        "subtitle_config": {"font": "DisplaySans", "position": "center"},
        "sort_order": 40,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "brand_clean",
        "name": "极简品牌",
        "description": "干净色块与强留白，适合产品解说与品牌短片。",
        "category": ["商业", "极简"],
        "preview_cover": "/static/templates/covers/brand_clean.png",
        "style_prefix": "极简品牌概念插画，大面积留白，有限色板（黑白+一强调色），几何构图，干净产品感，非写实摄影、非杂乱拼贴",
        "negative_prompt": "杂乱纹理，霓虹赛博，血腥，儿童粉彩堆砌，写实照片，真人，水印，画面乱文字",
        "default_ratio": "9:16",
        "shot_duration_min": 3,
        "shot_duration_max": 10,
        "llm_system_addon": "商业短句：卖点→场景→收束。每镜一个视觉焦点。全片统一极简品牌插画风。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.68,
            "character_prompt": "极简几何化人物或手部剪影，配色固定，低细节面部，全片外形一致",
            "extra_prompt": "大留白、有限色板、几何构图，竖屏品牌感",
        },
        "seedance_config": {
            "motion_bias": "色块轻移，极慢推近，干净无抖动",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "urban_editorial", "bgm_mood": "极简电子"},
        "subtitle_config": {"font": "DisplaySans", "position": "center"},
        "sort_order": 42,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "pixel_retro",
        "name": "像素复古科普",
        "description": "8-bit/16-bit 像素风，适合科技史与游戏化讲解。",
        "category": ["复古", "像素"],
        "preview_cover": "/static/templates/covers/pixel_retro.png",
        "style_prefix": "复古像素画，16位有限色板，清晰像素块，简单游戏场景，无抗锯齿",
        "negative_prompt": "平滑渐变，写实照片，模糊像素",
        "default_ratio": "16:9",
        "shot_duration_min": 3,
        "shot_duration_max": 12,
        "llm_system_addon": (
            "节奏偏游戏关卡感，信息点做成可辨识像素图标。"
            "涉及软件/系统/工具时，优先像素小人坐在电脑前操作系统、点击菜单、通关式演示流程。"
        ),
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "character_prompt": "16位像素小人操作员，坐在电脑前，有限色板，外形与调色全片不变",
            "extra_prompt": "像素小人操作系统界面，清晰像素块，无抗锯齿，游戏关卡式场景",
        },
        "seedance_config": {
            "motion_bias": "逐帧点击与屏幕切换，轻微视差滚动",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "retro_host", "bgm_mood": "8位好奇"},
        "subtitle_config": {"font": "PixelFont", "position": "bottom"},
        "sort_order": 50,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "retro_vhs",
        "name": "复古 VHS",
        "description": "磁带录像与扫描线质感，适合怀旧故事与年代感内容。",
        "category": ["复古", "电影感"],
        "preview_cover": "/static/templates/covers/retro_vhs.png",
        "style_prefix": "复古 VHS 概念插画，轻微色差与扫描线暗示，1980–90s 色调，圆角电视框感构图，怀旧氛围，非写实照片、非现代超清UI",
        "negative_prompt": "超清现代广告，赛博霓虹堆砌，写实照片，真人，儿童粉彩，水印，画面乱码文字",
        "default_ratio": "16:9",
        "shot_duration_min": 3,
        "shot_duration_max": 12,
        "llm_system_addon": "怀旧叙事，旁白可带年代感。全片统一 VHS 插画质感与角色外形。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "character_prompt": "怀旧风插画人物，年代感发型服装固定，轻微色差边缘，非照片，全片同一人设",
            "extra_prompt": "扫描线暗示、轻微色差、80/90年代色调，怀旧构图",
        },
        "seedance_config": {
            "motion_bias": "轻微磁带抖动感，慢推，色差微闪",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "retro_host", "bgm_mood": "怀旧合成器"},
        "subtitle_config": {"font": "SourceHanSans", "position": "bottom"},
        "sort_order": 52,
        "is_active": True,
        "is_premium": False,
    },
    {
        "id": "ink_guofeng",
        "name": "水墨国风",
        "description": "水墨留白与写意笔触，适合历史与文化短故事。",
        "category": ["国风", "水墨"],
        "preview_cover": "/static/templates/covers/ink_guofeng.png",
        "style_prefix": "中国水墨写意插画，富有表现力的笔触，大量留白，诗意氛围，淡雅墨色，非写实摄影",
        "negative_prompt": "写实照片，真人，真实人脸，霓虹，赛博朋克，日系动漫，欧美卡通，画面文字，字幕，水印",
        "default_ratio": "9:16",
        "shot_duration_min": 4,
        "shot_duration_max": 12,
        "llm_system_addon": "叙事偏意境与转折，台词可略文言白话混用，留白节奏。适合竖屏图文：每镜短标题+诗意副标题叠字，并写可朗读的旁白。",
        "seedream_config": {
            "ref_images": [],
            "strength": 0.7,
            "character_prompt": "水墨写意人物，简笔眉眼，宽袍或古装轮廓固定，墨色淡雅，全片同一人设",
            "extra_prompt": "大量留白，淡墨渲染，诗意意境，竖屏顶部可叠字",
        },
        "seedance_config": {
            "motion_bias": "墨晕渗开与消散，缓慢升降镜头，薄雾飘动",
            "character_consistency": True,
        },
        "audio_config": {"voice_preset": "guqin_narrator", "bgm_mood": "古筝氛围"},
        "subtitle_config": {"font": "KaiTi", "position": "top"},
        "sort_order": 60,
        "is_active": True,
        "is_premium": False,
    },
]
