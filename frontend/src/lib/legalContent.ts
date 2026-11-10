/** 联系页渠道与反馈主题。法务正文见 legalDocuments.ts。 */
import { SUPPORT_EMAIL } from './siteContact'

export type ContactChannel = {
  title: string
  desc: string
  href?: string
  actionLabel?: string
}

export const CONTACT_CHANNELS: ContactChannel[] = [
  {
    title: '邮箱支持',
    desc: '工作日一般 1–2 个工作日内回复；请附上账号邮箱与订单号（如有）。',
    href: `mailto:${SUPPORT_EMAIL}`,
    actionLabel: SUPPORT_EMAIL,
  },
  {
    title: '帮助中心',
    desc: '充值、下载、漫剧与工具等常见问题可先在帮助中心自助查询。',
    href: '/help',
    actionLabel: '前往帮助中心',
  },
  {
    title: '企业合作 / 对公转账',
    desc: '企业批量充值、API 合作或发票需求，请邮件说明公司名称与需求，我们会安排对接。',
    href: `mailto:${SUPPORT_EMAIL}?subject=PRINTFILM%20企业合作`,
    actionLabel: '发送合作邮件',
  },
]

export const CONTACT_TOPICS = [
  '账号与登录',
  '充值与到账',
  '创作任务异常',
  '下载与素材',
  '隐私与账号注销',
  '其他',
] as const
