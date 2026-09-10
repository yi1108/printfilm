/** 法律与联系页文案：用户协议、隐私政策、联系渠道 */

export type LegalSection = {
  title: string
  paragraphs?: string[]
  bullets?: string[]
}

export type LegalDoc = {
  slug: 'terms' | 'privacy'
  title: string
  updatedAt: string
  intro: string
  sections: LegalSection[]
}

export const LEGAL_DOCS: Record<'terms' | 'privacy', LegalDoc> = {
  terms: {
    slug: 'terms',
    title: '用户协议',
    updatedAt: '2026-08-17',
    intro:
      '欢迎使用 PRINTFILM（以下简称「本平台」）。在注册或使用本平台服务前，请仔细阅读本协议。一旦您开始使用，即视为已阅读并同意以下条款。',
    sections: [
      {
        title: '1. 服务说明',
        paragraphs: [
          'PRINTFILM 提供 AI 漫剧、AI短视频及创作工具（含文生图、图生图、文生视频等）相关服务。服务内容可能随产品迭代调整，我们将尽可能在页面或公告中说明重大变更。',
          '本平台按实际上游模型用量计费，余额充值后永久有效，不设强制订阅。具体价格与赠送规则以定价页及下单时展示为准。',
        ],
      },
      {
        title: '2. 账号与安全',
        bullets: [
          '您应使用真实、有效的信息进行注册，并对账号下的全部行为负责。',
          '请妥善保管登录凭证；因账号泄露、共用导致的损失，由您自行承担。',
          '如发现未经授权的使用，请及时通过「联系我们」告知我们。',
          '我们有权在发现违规、欺诈或滥用时限制、冻结或注销相关账号。',
        ],
      },
      {
        title: '3. 内容与知识产权',
        paragraphs: [
          '您输入的提示词、脚本、素材等仍归您或原权利人所有。您保证对上传内容拥有合法权利，不得侵犯第三方知识产权、肖像权、隐私权等。',
          '使用 AI 生成的内容可能存在不准确、不完整或与预期不符的情况，请在正式发布前自行审核。因您对外发布、商用使用生成内容引发的纠纷，由您自行负责。',
          '本平台的界面、商标、软件与文档等知识产权归 PRINTFILM 或相关权利人所有，未经许可不得复制、反向工程或用于与本服务无关的商业用途。',
        ],
      },
      {
        title: '4. 计费与充值',
        bullets: [
          '生成类任务按上游 token 或约定单价计费；开始任务时可能预扣估算金额，结束后按实际用量结算（多退少补）。',
          '充值通过支付宝、微信支付等渠道完成，到账以系统记录为准。',
          '除法律法规另有规定或本平台明确约定外，已到账的充值余额一般不予退款。',
          '若因系统故障导致重复扣款或未到账，请保留订单号并联系客服核实处理。',
        ],
      },
      {
        title: '5. 禁止行为',
        bullets: [
          '利用本服务制作、传播违法、色情、暴力、仇恨、欺诈或侵犯他人权益的内容。',
          '对平台进行攻击、爬取、绕过计费、滥用接口或干扰其他用户。',
          '未经授权转售账号、批量注册或从事其他损害平台公平运营的行为。',
        ],
      },
      {
        title: '6. 免责与责任限制',
        paragraphs: [
          '在法律允许的范围内，本平台对因网络故障、第三方服务中断、不可抗力导致的服务中断或数据损失不承担责任。',
          'AI 输出仅为辅助创作工具，不构成专业建议。因依赖生成内容造成的直接或间接损失，本平台不承担超出您已支付服务费范围以外的责任（法律另有强制规定的除外）。',
        ],
      },
      {
        title: '7. 协议变更与终止',
        paragraphs: [
          '我们可能适时修订本协议，修订后的版本将在本页面公布，并以「更新日期」为准。若您继续使用服务，视为接受修订后的协议。',
          '您可随时停止使用并申请注销账号；我们也可在您严重违反本协议时终止向您提供服务。',
        ],
      },
      {
        title: '8. 联系方式',
        paragraphs: [
          '如对本协议有疑问，请前往「联系我们」页面提交反馈，或发送邮件至 support@printfilm.com。',
        ],
      },
    ],
  },
  privacy: {
    slug: 'privacy',
    title: '隐私政策',
    updatedAt: '2026-08-17',
    intro:
      'PRINTFILM 重视您的隐私。本政策说明我们如何收集、使用、存储与保护您的个人信息。使用本平台即表示您理解本政策所述处理方式。',
    sections: [
      {
        title: '1. 我们收集的信息',
        bullets: [
          '账号信息：注册邮箱、昵称、头像、登录与鉴权相关数据。',
          '使用数据：创作项目、提示词、生成任务状态、工具运行记录、资产库内容等业务数据。',
          '计费信息：余额、冻结金额、充值订单、用量与扣费明细（支付由第三方渠道完成，我们不存储完整银行卡号等敏感支付信息）。',
          '技术日志：IP、浏览器类型、访问时间等用于安全与故障排查的必要日志。',
        ],
      },
      {
        title: '2. 信息的使用目的',
        bullets: [
          '提供、维护与改进漫剧、科普与工具等创作服务。',
          '完成身份验证、计费结算、订单查询与客服支持。',
          '保障账号与系统安全，防范欺诈与滥用。',
          '在获得同意或法律法规允许的情况下，向您发送服务通知或产品更新。',
        ],
      },
      {
        title: '3. 存储与第三方',
        paragraphs: [
          '您的媒体与创作文件可能存储于云端对象存储（如阿里云 OSS），以便预览与下载。',
          '支付由易支付等合作方处理；大模型推理由上游模型服务商完成。我们仅向其提供完成服务所必需的数据，并要求其按约定保护信息。',
          '除法律法规要求、获得您明确同意，或为保护本平台及用户合法权益所必需外，我们不会向无关第三方出售您的个人信息。',
        ],
      },
      {
        title: '4. Cookie 与本地存储',
        paragraphs: [
          '为维持登录态与偏好设置，我们可能使用 Cookie 或浏览器本地存储（如 token）。您可在浏览器中清除，但这可能导致需要重新登录。',
        ],
      },
      {
        title: '5. 您的权利',
        bullets: [
          '查阅、更正账号资料（可在个人中心操作）。',
          '导出或下载您有权访问的创作成果（在产品功能允许范围内）。',
          '申请注销账号；注销后我们将按法规要求删除或匿名化相关个人信息，法律法规要求保留的除外。',
          '对隐私相关问题进行咨询或投诉。',
        ],
      },
      {
        title: '6. 未成年人保护',
        paragraphs: [
          '本平台主要面向具备完全民事行为能力的用户。若您为未成年人，请在监护人指导下阅读本政策并使用服务。',
        ],
      },
      {
        title: '7. 政策更新',
        paragraphs: [
          '我们可能更新本政策，并在本页公布最新版本与更新日期。重大变更时，我们会通过站内提示等方式尽量告知。',
        ],
      },
      {
        title: '8. 联系我们',
        paragraphs: [
          '如对本政策有任何疑问，请访问「联系我们」或发送邮件至 support@printfilm.com。',
        ],
      },
    ],
  },
}

export const LEGAL_DOCS_EN: Record<'terms' | 'privacy', LegalDoc> = {
  terms: {
    slug: 'terms',
    title: 'Terms of Service',
    updatedAt: '2026-08-17',
    intro:
      'Welcome to PRINTFILM (“the Platform”). Please read these terms before you register or use the service. Using the Platform means you have read and agree to them.',
    sections: [
      {
        title: '1. The service',
        paragraphs: [
          'PRINTFILM provides AI drama, explainer video, and creation tools (including text-to-image, image-to-image, and text-to-video). Features may change as the product evolves; we will try to note material changes on the site or in notices.',
          'Billing follows actual upstream model usage. Topped-up balance does not expire and there is no forced subscription. Prices and bonuses follow the Pricing page and the checkout screen.',
        ],
      },
      {
        title: '2. Accounts and security',
        bullets: [
          'Register with accurate information and you are responsible for activity under the account.',
          'Keep credentials safe. Losses from leaks or sharing are yours to bear.',
          'If you see unauthorized use, tell us via Contact.',
          'We may limit, freeze, or close accounts for abuse, fraud, or policy violations.',
        ],
      },
      {
        title: '3. Content and IP',
        paragraphs: [
          'Prompts, scripts, and uploads remain yours or the original rights holder’s. You warrant you have the right to upload them and will not infringe IP, portrait, or privacy rights.',
          'AI output may be inaccurate or unexpected. Review it before publishing. Disputes from your public or commercial use are your responsibility.',
          'The Platform UI, marks, software, and docs belong to PRINTFILM or licensors. Do not copy, reverse-engineer, or use them outside this service without permission.',
        ],
      },
      {
        title: '4. Billing and top-ups',
        bullets: [
          'Generation jobs are billed by upstream tokens or agreed unit prices. We may pre-authorize an estimate and settle the real usage afterward.',
          'Top-ups go through Alipay, WeChat Pay, and similar channels. Arrival follows system records.',
          'Except where law requires otherwise or we explicitly agree, arrived credits are generally non-refundable.',
          'If a fault causes a double charge or missing credit, keep the order ID and contact support.',
        ],
      },
      {
        title: '5. Prohibited use',
        bullets: [
          'Do not create or spread illegal, pornographic, violent, hateful, fraudulent, or otherwise infringing content.',
          'Do not attack, scrape, bypass billing, abuse APIs, or disrupt other users.',
          'Do not resell accounts, bulk-register, or otherwise harm fair operation.',
        ],
      },
      {
        title: '6. Disclaimers',
        paragraphs: [
          'To the extent allowed by law, we are not liable for outages or data loss from network faults, third-party interruptions, or force majeure.',
          'AI output is a creation aid, not professional advice. We are not liable beyond fees you paid for losses from relying on generated content, except where law requires otherwise.',
        ],
      },
      {
        title: '7. Changes and termination',
        paragraphs: [
          'We may revise these terms and post the new version here with an updated date. Continued use means you accept the revision.',
          'You may stop using the service and request account deletion. We may also stop serving you if you seriously breach these terms.',
        ],
      },
      {
        title: '8. Contact',
        paragraphs: [
          'Questions about these terms: use Contact or email support@printfilm.com.',
        ],
      },
    ],
  },
  privacy: {
    slug: 'privacy',
    title: 'Privacy Policy',
    updatedAt: '2026-08-17',
    intro:
      'PRINTFILM respects your privacy. This policy explains how we collect, use, store, and protect personal information. Using the Platform means you understand this processing.',
    sections: [
      {
        title: '1. Information we collect',
        bullets: [
          'Account data: email, display name, avatar, and authentication data.',
          'Usage data: projects, prompts, job status, tool runs, and asset library content.',
          'Billing data: balance, holds, top-up orders, and usage ledgers (payment is handled by third parties; we do not store full card numbers).',
          'Technical logs: IP, browser type, and access time for security and debugging.',
        ],
      },
      {
        title: '2. How we use it',
        bullets: [
          'Provide, maintain, and improve drama, explainer, and tool services.',
          'Identity checks, billing, order queries, and support.',
          'Account and system security, fraud and abuse prevention.',
          'Service notices or product updates where you consent or law allows.',
        ],
      },
      {
        title: '3. Storage and third parties',
        paragraphs: [
          'Media and project files may live in cloud object storage (such as Alibaba Cloud OSS) for preview and download.',
          'Payments go through partners such as Epay; model inference goes through upstream providers. We share only what is needed to complete the service.',
          'We do not sell personal information to unrelated third parties except as required by law, with your consent, or to protect the Platform and users.',
        ],
      },
      {
        title: '4. Cookies and local storage',
        paragraphs: [
          'We may use cookies or local storage (such as a token) to keep you signed in and remember preferences. Clearing them may require signing in again.',
        ],
      },
      {
        title: '5. Your rights',
        bullets: [
          'View and correct profile data in Account.',
          'Export or download creative output where the product allows.',
          'Request account deletion; we will delete or anonymize personal data as required, except records the law keeps.',
          'Ask questions or complain about privacy.',
        ],
      },
      {
        title: '6. Children',
        paragraphs: [
          'The Platform is intended for users with full civil capacity. If you are a minor, read this policy and use the service with a guardian.',
        ],
      },
      {
        title: '7. Policy updates',
        paragraphs: [
          'We may update this policy and post the latest version and date here. For material changes we will try to notify you in-product.',
        ],
      },
      {
        title: '8. Contact',
        paragraphs: [
          'Questions: use Contact or email support@printfilm.com.',
        ],
      },
    ],
  },
}

// 按界面语言取用户协议 / 隐私政策
export function getLegalDoc(slug: 'terms' | 'privacy', locale: string): LegalDoc {
  const pack = locale === 'en' ? LEGAL_DOCS_EN : LEGAL_DOCS
  return pack[slug]
}

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
    href: 'mailto:support@printfilm.com',
    actionLabel: 'support@printfilm.com',
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
    href: 'mailto:support@printfilm.com?subject=PRINTFILM%20企业合作',
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
