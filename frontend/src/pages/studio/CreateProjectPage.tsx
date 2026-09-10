import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, defaultsFromTemplate } from '../../api'
import type { Template } from '../../api'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import AppShell from '../../components/layout/AppShell'
import Stepper from '../../components/ui/Stepper'
import PillTabs from '../../components/ui/PillTabs'
import ComingSoon from '../../components/ui/ComingSoon'
import { IconChevronLeft, IconRefresh, IconSparkles } from '../../components/ui/Icons'
import { CATEGORY_ORDER } from '../../lib/categories'
import { CREATE_STEPS } from '../../lib/status'

type Inspiration = {
  title: string
  theme: string
  script: string
}

const INSPIRATION_POOL: Inspiration[] = [
  {
    title: '黑洞是如何形成的',
    theme: '黑洞是如何形成的？用通俗方式讲清恒星坍缩、事件视界与时空弯曲，面向中学生。',
    script:
      '夜空里最神秘的天体之一，就是黑洞。\n\n' +
      '当一颗足够大的恒星燃料烧尽，核心会在引力下剧烈坍缩，密度高到连光都逃不出去，事件视界就此诞生。\n\n' +
      '它不是宇宙吸尘器，而是时空被严重弯曲的区域。靠近它，时间流逝也会变得奇怪。\n\n' +
      '记住：质量够大、坍缩够猛，黑洞就会出现。下一次看科普新闻，你就能分清传说与科学。',
  },
  {
    title: '为什么天空是蓝色的',
    theme: '为什么天空是蓝色的？用瑞利散射解释阳光、空气分子与傍晚火烧云，适合科普入门。',
    script:
      '抬头一看，白天的天空常常是蓝的，这是巧合吗？\n\n' +
      '阳光看起来发白，其实包含多种颜色。空气分子对蓝光散射更强，蓝光更容易被「弹」向四面八方，于是我们眼里的天空偏蓝。\n\n' +
      '早晚太阳更低，光穿过更厚大气，蓝光散得更干净，剩下的红橙光就染红了天边。\n\n' +
      '所以天空的颜色，是光与空气的一场合作。',
  },
  {
    title: 'AI 如何改变生活',
    theme: 'AI 如何改变生活：从推荐、语音助手到医疗影像，讲清便利与需要警惕的偏见。',
    script:
      '打开手机，推荐视频、导航路线、语音助手——人工智能已经悄悄进了日常。\n\n' +
      '它擅长从海量数据里找规律：帮医生看影像线索，帮工厂预判故障，也帮你把搜索变成对话。\n\n' +
      '但 AI 不是魔法。数据有偏见，模型会犯错，隐私也需要边界。真正有用的，是把 AI 当工具，而不是当权威。\n\n' +
      '理解它能做什么、不能做什么，你才能用得更聪明。',
  },
  {
    title: '火星上的一天',
    theme: '火星上的一天长什么样？对比地球日长、气温、沙尘与人类基地想象，做成场景化科普。',
    script:
      '想象你在火星醒来：太阳更远更小，天空偏奶油色，一天大约 24 小时 39 分钟。\n\n' +
      '白天可能「温暖」到零下，夜晚更冷。薄薄的二氧化碳大气留不住热量，沙尘暴偶尔遮天。\n\n' +
      '科学家仍在规划基地：要防辐射、造氧气、种食物。火星不是第二地球，却是最近的外太空课堂。\n\n' +
      '了解火星的一天，就是在预习人类下一次远行。',
  },
  {
    title: '梦的力量',
    theme: '梦的力量：睡眠周期、快速眼动与记忆整理，用故事讲清做梦如何帮助大脑「复盘」。',
    script:
      '你睡着以后，大脑并没有下班。\n\n' +
      '进入快速眼动睡眠时，大脑像在回放白天的片段，拼接成奇幻的梦。科学家认为，这有助于整理记忆、调节情绪。\n\n' +
      '睡不够，注意力和创造力都会打折；规律睡眠，则像给大脑做夜间维护。\n\n' +
      '下次做怪梦，别只觉得荒唐——那可能是大脑在加班学习。',
  },
  {
    title: '一只流浪猫的春天',
    theme: '一只流浪猫的春天：用拟人旁白讲城市生态、投喂边界与人宠共处，温暖向科普叙事。',
    script:
      '春天来了，巷口的橘猫开始换毛，也开始寻找更安全的角落。\n\n' +
      '城市里的流浪动物，靠的是残存野性与人类不经意的善意。科学投喂、绝育与尊重距离，比冲动更重要。\n\n' +
      '它们不是风景，也不是麻烦，而是城市生态的一部分。\n\n' +
      '这个春天，愿每一只猫，都能遇见更稳妥的明天。',
  },
  {
    title: '光合作用的秘密',
    theme: '光合作用的秘密：叶子如何把阳光变成糖，讲清叶绿体、能量转化与地球氧气来源。',
    script:
      '绿叶不只是装饰，它们是地球上最安静的化工厂。\n\n' +
      '叶绿体抓住阳光，把水和二氧化碳做成糖，并释放氧气。没有这个过程，绝大多数食物链都会断裂。\n\n' +
      '你呼吸的氧气、餐桌上的米饭和蔬菜，都间接来自这场光的魔法。\n\n' +
      '看懂光合作用，就看懂了生命运转的底层账本。',
  },
  {
    title: '地震来了怎么办',
    theme: '地震来了怎么办：用场景教学讲清震前准备、避险姿势与谣言辨别，实用安全科普。',
    script:
      '地面突然晃起来，第一反应往往是慌。\n\n' +
      '正确做法是就近伏地、掩护、抓稳，远离窗户与高架物；不要一窝蜂挤电梯。提前准备应急包，比临时抱佛脚更管用。\n\n' +
      '震后还要警惕余震和谣言。权威信息、互助秩序，才是真正的安全感。\n\n' +
      '懂一点地震知识，关键时刻就能多一分从容。',
  },
  {
    title: '咖啡因如何提神',
    theme: '咖啡因如何提神：腺苷受体、耐受与睡眠代价，帮上班族科学喝咖啡。',
    script:
      '困的时候来杯咖啡，真的是「叫醒大脑」吗？\n\n' +
      '咖啡因会抢占腺苷的位置，让你暂时感觉不困。但它不能替代睡眠，下午喝太多，夜里更容易翻来覆去。\n\n' +
      '逐渐耐受后，同样一杯效果会变弱。更聪明的用法是：需要专注时再用，并给睡眠留窗口。\n\n' +
      '提神可以靠咖啡，恢复还是得靠睡。',
  },
  {
    title: '塑料去哪了',
    theme: '塑料去哪了：微塑料、海洋环流与可替代材料，做成环保主题科普短片。',
    script:
      '扔掉的塑料袋，真的消失了吗？\n\n' +
      '多数只是被撕成更小的碎片。微塑料进入河流与海洋，再进入食物链，最终可能回到我们的餐桌。\n\n' +
      '减少一次性塑料、做好分类、推动更好的材料，比事后清理便宜得多。\n\n' +
      '问「塑料去哪了」，其实是在问：我们愿为未来留什么。',
  },
  {
    title: '疫苗为什么有效',
    theme: '疫苗为什么有效：用「预演」比喻讲清抗原、抗体与群体免疫，澄清常见误解。',
    script:
      '疫苗不是药，更像给免疫系统发的预告片。\n\n' +
      '它让身体提前认识病原体的关键特征，真正遇到时能更快调动抗体。这不是改写基因，而是训练记忆。\n\n' +
      '足够多人获得保护，传播链会被削弱，这就是群体免疫的意义。\n\n' +
      '科学接种，是把自己和身边人一起放进更安全的网络。',
  },
  {
    title: '潮汐的涨落',
    theme: '潮汐为何涨落：月球引力、离心效应与大潮小潮，海边场景化讲解。',
    script:
      '海边的人最懂：水位会按时涨、按时退。\n\n' +
      '主要推手是月球的引力，太阳也来凑热闹。地球、月球、太阳排成一线时，潮差更大，就是大潮。\n\n' +
      '潮汐还影响航行、发电甚至生物节律。抬头看月亮，脚下的海也在回应。\n\n' +
      '涨落之间，是天地引力的可见痕迹。',
  },
]

const PAGE_SIZE = 6

function isDefaultTitle(value: string) {
  const t = value.trim()
  return !t || t === '未命名作品'
}

function deriveTitle(text: string) {
  const line = text
    .trim()
    .split(/\n/)[0]
    .replace(/["""'']/g, '')
    .replace(/[。！？!?：:].*$/, '')
    .trim()
  if (!line) return '未命名作品'
  return line.slice(0, 18)
}

export default function CreateProjectPage() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [templates, setTemplates] = useState<Template[]>([])
  const [templateId, setTemplateId] = useState(params.get('template') || '')
  const [category, setCategory] = useState('全部')
  const [q, setQ] = useState('')
  const [inputTab, setInputTab] = useState('一句话主题')
  const [sourceText, setSourceText] = useState(INSPIRATION_POOL[0].theme)
  const [title, setTitle] = useState(INSPIRATION_POOL[0].title)
  const [titleTouched, setTitleTouched] = useState(false)
  const [inspPage, setInspPage] = useState(0)
  const [busy, setBusy] = useState(false)
  const [aiBusy, setAiBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      nav('/auth')
      return
    }
    api.me().catch(() => nav('/auth'))
    api.templates().then((list) => {
      setTemplates(list)
      const fromUrl = params.get('template') || ''
      setTemplateId((prev) => prev || fromUrl || list[0]?.id || '')
    })
  }, [nav, params])

  const categories = useMemo(() => {
    const found = new Set<string>()
    for (const t of templates) {
      for (const c of t.category || []) {
        if (CATEGORY_ORDER.includes(c)) found.add(c)
      }
    }
    return ['全部', '热门推荐', ...CATEGORY_ORDER.filter((c) => found.has(c))]
  }, [templates])

  const filtered = useMemo(() => {
    let list = templates
    if (category === '热门推荐') list = [...templates].sort((a, b) => a.sort_order - b.sort_order).slice(0, 8)
    else if (category !== '全部') list = list.filter((t) => (t.category || []).includes(category))
    if (q.trim()) {
      const s = q.trim().toLowerCase()
      list = list.filter((t) => t.name.toLowerCase().includes(s))
    }
    return list
  }, [templates, category, q])

  const selected = templates.find((t) => t.id === templateId)
  const sourceType = inputTab === '粘贴完整文案' ? 'script' : 'theme'
  const disabledInput = inputTab === '导入文章链接' || inputTab === '上传文档'
  const inspTotal = Math.ceil(INSPIRATION_POOL.length / PAGE_SIZE)
  const inspirations = INSPIRATION_POOL.slice(inspPage * PAGE_SIZE, inspPage * PAGE_SIZE + PAGE_SIZE)

  function applyInspiration(item: Inspiration) {
    if (sourceType === 'script') {
      setInputTab('粘贴完整文案')
      setSourceText(item.script.slice(0, 8000))
    } else {
      setInputTab('一句话主题')
      setSourceText(item.theme.slice(0, 100))
    }
    setTitle(item.title.slice(0, 24))
    setTitleTouched(false)
    setError('')
  }

  function shuffleInspirations() {
    setInspPage((p) => (p + 1) % inspTotal)
  }

  async function aiExpand() {
    if (disabledInput) {
      setError('该输入方式即将推出，请使用一句话主题或粘贴文案')
      return
    }
    const seed = sourceText.trim() || title.trim() || '人工智能如何改变生活'
    setAiBusy(true)
    setError('')
    try {
      const mode = sourceType === 'script' ? 'script' : 'theme'
      const result = await api.expandContent(seed, mode)
      setSourceText(result.content.slice(0, mode === 'theme' ? 100 : 8000))
      if (!titleTouched || isDefaultTitle(title)) {
        setTitle(result.title.slice(0, 24))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 生成失败')
    } finally {
      setAiBusy(false)
    }
  }

  async function next() {
    if (!templateId || !sourceText.trim()) {
      setError('请选择模板并填写主题内容')
      return
    }
    if (disabledInput) {
      setError('该输入方式即将推出，请使用一句话主题或粘贴文案')
      return
    }
    setBusy(true)
    setError('')
    try {
      const tpl = templates.find((t) => t.id === templateId)
      const d = tpl ? defaultsFromTemplate(tpl) : undefined
      const modeParam = params.get('mode')
      const pipeline_mode: 'full' | 'image_text' =
        modeParam === 'image_text' || modeParam === 'full' ? modeParam : 'full'
      const finalTitle =
        title.trim() || deriveTitle(sourceText) || sourceText.trim().slice(0, 24) || '未命名作品'
      const project = await api.createProject({
        template_id: templateId,
        title: finalTitle,
        source_type: sourceType,
        source_text: sourceText.trim(),
        resolution_mode: 'preview',
        pipeline_mode,
        output_ratio: d?.output_ratio || '16:9',
        voice_id: d?.voice_id,
      })
      nav(`/studio/${project.id}/style`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AppShell active="studio" wide>
      <header className="pf-page-head">
        <div className="pf-page-head-row">
          <div>
            <button type="button" className="pf-back" onClick={() => nav('/')}>
              <IconChevronLeft size={18} />
              新建项目 / 开始创作
            </button>
            <h1 className="pf-page-title">创建项目</h1>
          </div>
          <Stepper steps={CREATE_STEPS} current={1} doneThrough={0} />
        </div>
      </header>

      <div className="pf-create">
        <aside className="pf-create-col">
          <h3>选择模板</h3>
          <div className="pf-search">
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索模板…" />
          </div>
          <PillTabs items={categories.slice(0, 6)} value={category} onChange={setCategory} ariaLabel="模板分类" />
          <div className="pf-tpl-list" style={{ marginTop: '0.75rem' }}>
            {filtered.map((t) => (
              <button
                key={t.id}
                type="button"
                className={templateId === t.id ? 'pf-tpl-mini selected' : 'pf-tpl-mini'}
                onClick={() => setTemplateId(t.id)}
              >
                <img src={api.assetUrl(t.preview_cover)} alt="" />
                <div>
                  <strong>{t.name}</strong>
                  <span>
                    {t.default_ratio} · {(t.category || [])[0] || '通用'}
                  </span>
                </div>
              </button>
            ))}
          </div>
          <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" style={{ marginTop: '0.75rem' }} disabled>
            加载更多模板 <ComingSoon />
          </button>
        </aside>

        <section className="pf-create-col">
          <h3>输入内容</h3>
          <div className="pf-input-tabs">
            {['一句话主题', '粘贴完整文案', '导入文章链接', '上传文档'].map((tab) => (
              <button
                key={tab}
                type="button"
                className={['pf-pill', inputTab === tab ? 'lime active' : ''].join(' ')}
                onClick={() => setInputTab(tab)}
              >
                {tab}
                {(tab === '导入文章链接' || tab === '上传文档') && (
                  <>
                    {' '}
                    <ComingSoon />
                  </>
                )}
              </button>
            ))}
          </div>

          <label className="pf-field">
            <span className="pf-field-label">项目名称</span>
            <input
              className="pf-field-input"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value)
                setTitleTouched(true)
              }}
              onBlur={() => {
                if (isDefaultTitle(title) && sourceText.trim()) {
                  setTitle(deriveTitle(sourceText))
                  setTitleTouched(false)
                }
              }}
              placeholder="将根据内容自动填充"
            />
          </label>

          <div className="pf-textarea-wrap">
            <div className="pf-textarea-toolbar">
              <button
                type="button"
                className="pf-btn pf-btn-ai pf-btn-sm pf-btn-icon"
                disabled={aiBusy || busy || disabledInput}
                onClick={aiExpand}
              >
                <IconSparkles size={14} />
                {aiBusy ? '生成中…' : sourceType === 'script' ? 'AI 扩写文案' : 'AI 生成主题'}
              </button>
              <span className="pf-muted" style={{ fontSize: '0.75rem' }}>
                {sourceType === 'script' ? '可从一句话扩成完整口播' : '补全受众与知识点'}
              </span>
            </div>
            <textarea
              value={sourceText}
              onChange={(e) => {
                const next = e.target.value.slice(0, sourceType === 'theme' ? 100 : 8000)
                setSourceText(next)
                if (!titleTouched || isDefaultTitle(title)) {
                  setTitle(deriveTitle(next))
                }
              }}
              disabled={disabledInput}
              placeholder={
                disabledInput
                  ? '该方式即将推出'
                  : sourceType === 'theme'
                    ? '例如：黑洞是如何形成的？用通俗方式讲清引力与时空'
                    : '粘贴或 AI 生成完整口播文案…'
              }
            />
            {sourceType === 'theme' ? (
              <span className="pf-char-count">{sourceText.length}/100</span>
            ) : (
              <span className="pf-char-count">{sourceText.length} 字</span>
            )}
          </div>

          <div className="pf-inspire">
            <div className="pf-inspire-head">
              <strong>灵感示例</strong>
              <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm pf-btn-icon" onClick={shuffleInspirations}>
                <IconRefresh size={14} />
                换一批
              </button>
            </div>
            <div className="pf-chips">
              {inspirations.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  className="pf-chip"
                  title={sourceType === 'script' ? item.script.slice(0, 80) : item.theme}
                  onClick={() => applyInspiration(item)}
                >
                  {item.title}
                </button>
              ))}
            </div>
            <p className="pf-muted" style={{ fontSize: '0.78rem', margin: '0.55rem 0 0' }}>
              点击示例会填充完整{sourceType === 'script' ? '文案' : '主题'}并自动写入项目名称
            </p>
          </div>

          <div className="pf-hint" style={{ marginTop: '1rem' }}>
            主题越具体，AI 越容易生成准确的科普分镜与旁白。可写清受众与核心知识点。
          </div>
          {error ? <BillingErrorNotice message={error} /> : null}
        </section>

        <aside className="pf-create-col">
          <h3>创作摘要</h3>
          {selected ? (
            <div style={{ marginBottom: '0.85rem' }}>
              <img
                src={api.assetUrl(selected.preview_cover)}
                alt=""
                style={{ width: '100%', borderRadius: 12, aspectRatio: '16/9', objectFit: 'cover' }}
              />
              <strong style={{ display: 'block', marginTop: '0.5rem' }}>{selected.name}</strong>
              <p className="pf-muted" style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
                {selected.description}
              </p>
            </div>
          ) : (
            <p className="pf-muted">请选择模板</p>
          )}
          <div className="pf-summary-row">
            <span>作品名称</span>
            <span>{title.trim() || '未命名作品'}</span>
          </div>
          <div className="pf-summary-row">
            <span>输出模式</span>
            <span>{selected?.default_ratio === '9:16' ? '视频 · 9:16' : '视频 · 16:9'}</span>
          </div>
          <div className="pf-summary-row">
            <span>预估时长</span>
            <span>~1–3 分钟</span>
          </div>
          <div className="pf-summary-row">
            <span>语言</span>
            <span>中文（普通话）</span>
          </div>
          <div className="pf-summary-row">
            <span>输入方式</span>
            <span>{inputTab}</span>
          </div>
          <button
            type="button"
            className="pf-btn pf-btn-lime pf-btn-block pf-btn-lg pf-btn-icon"
            style={{ marginTop: '1.25rem' }}
            disabled={busy || aiBusy || !templateId || !sourceText.trim()}
            onClick={next}
          >
            {busy ? '创建中…' : '下一步：风格配置'}
            {!busy ? <span aria-hidden>→</span> : null}
          </button>
          <button
            type="button"
            className="pf-btn pf-btn-ghost pf-btn-block pf-btn-sm pf-btn-icon"
            style={{ marginTop: '0.55rem' }}
            disabled={aiBusy || busy || disabledInput}
            onClick={aiExpand}
          >
            <IconSparkles size={14} />
            {aiBusy ? 'AI 生成中…' : '不够完整？让 AI 帮你写'}
          </button>
          <p className="pf-muted" style={{ fontSize: '0.78rem', marginTop: '0.5rem' }}>
            下一步可自定义风格、画面与配音。
          </p>
        </aside>
      </div>
    </AppShell>
  )
}
