/** 帮助中心共用文案：分类、上手步骤、常见问题 */

export type HelpFaqItem = {
  q: string
  a: string
}

export type HelpCatItem = {
  id: string
  title: string
  desc: string
  href: string
}

export type HelpGuideStep = {
  n: string
  title: string
  body: string
}

export const HELP_CATS: HelpCatItem[] = [
  { id: 'start', title: '快速开始', desc: '工作台选产品入口', href: '/' },
  { id: 'drama', title: '漫剧创作', desc: '剧本 · 分集 · 成片', href: '/drama' },
  { id: 'kepu', title: 'AI短视频', desc: '分镜流水线与成片', href: '/history' },
  { id: 'tools', title: '创作工具', desc: '文生图 / 图生图 / 视频', href: '/tools' },
  { id: 'settings', title: '个人中心', desc: '项目 · 记录 · 下载', href: '/settings?tab=tools' },
  { id: 'billing', title: '充值说明', desc: '按量计费，余额永久有效', href: '/pricing' },
]

export const HELP_GUIDE_STEPS: HelpGuideStep[] = [
  {
    n: '01',
    title: '选创作入口',
    body: '工作台进入「AI 漫剧」或「AI短视频」；单点能力也可从顶栏「工具」进入文生图、图生图、文生视频等。',
  },
  {
    n: '02',
    title: '配置并生成',
    body: '漫剧：创意 → 大纲 → 资产 → 分集；科普：主题 → 风格 → 分镜 → 成片；工具：填提示词或上传素材后点生成。',
  },
  {
    n: '03',
    title: '审阅与迭代',
    body: '漫剧 / 科普可单镜重绘、重生视频或重配音，不必整片重做。工具结果可在工作台预览后再次生成。',
  },
  {
    n: '04',
    title: '保存与下载',
    body: '结果会写入云端存储。科普在历史页下载；漫剧在项目工作台查看；工具创作在个人中心查看详情并下载。',
  },
]

export const HELP_FAQ_ITEMS: HelpFaqItem[] = [
  {
    q: '第一次使用从哪开始？',
    a: '打开工作台，选择「AI 漫剧」或「AI短视频」。漫剧适合分集叙事与角色一致性；AI短视频适合短视频分镜流水线。若只要单张图或短片段，可直接进入「工具」。',
  },
  {
    q: '「AI 视频」和「静图成片」有什么区别？',
    a: 'AI 视频镜头运动更强、成本更高；静图成片（图文视频）以画面 + 旁白为主，更快更稳，适合讲解类科普。新建科普项目时按需求选择即可。',
  },
  {
    q: '生成中可以离开页面吗？',
    a: '可以。任务在服务端继续执行。科普可回「科普」历史页看进度；漫剧回对应项目工作台；工具视频任务请尽量停留在当前页等待完成，或稍后在个人中心查看状态。',
  },
  {
    q: '工具中心能做什么？',
    a: '已开放文生图、图生图、图生产品、文生视频、视频生视频与电商拼图。登录后进入「工具」选择对应能力，填写提示词或上传素材即可生成。',
  },
  {
    q: '工具生成结果保存在哪里？',
    a: '每次成功生成都会写入创作记录，媒体文件同步到云端对象存储（OSS）。可在头像 → 个人中心 →「工具创作」查看封面、状态与提示词。',
  },
  {
    q: '如何查看和下载工具结果？',
    a: '打开个人中心「工具创作」，点击「查看」可预览大图或视频；点击「下载」将从云端地址保存到本地。生成页右侧成功后也会提示可前往个人中心回看。',
  },
  {
    q: '成片或素材在哪里下载？',
    a: '科普成片：顶栏「科普」历史页，已完成项目可下载或打包。漫剧：进入对应项目工作台查看分镜与成片。全局资产：顶栏「资产」管理角色、场景、道具与音色。',
  },
  {
    q: '个人中心有哪些内容？',
    a: '包含账号信息、漫剧项目、科普历史、工具创作记录、资产管理入口，以及订阅与余额。团队、API、通知偏好等能力仍在建设中。',
  },
  {
    q: '如何充值？余额怎么扣？',
    a: '打开「定价」选择充值档位，支持支付宝与微信支付；未登录会先引导登录。按实际调用量扣费，余额永久有效，无强制订阅。用量可在定价页或个人中心「订阅与余额」查看。',
  },
  {
    q: '生成失败或画面不符合预期怎么办？',
    a: '可调整提示词、反向提示词或参考图后重试；漫剧 / 科普支持单镜重生。若反复失败，请检查网络与余额，或稍后重试。敏感内容可能被模型安全策略拦截。',
  },
]

// 按关键词过滤常见问题
export function filterHelpFaq(items: HelpFaqItem[], raw: string): HelpFaqItem[] {
  const needle = raw.trim().toLowerCase()
  if (!needle) return items
  return items.filter(
    (item) => item.q.toLowerCase().includes(needle) || item.a.toLowerCase().includes(needle),
  )
}
