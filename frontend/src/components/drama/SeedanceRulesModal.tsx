/** Seedance 传值与脚本规则说明弹窗（分集编辑页，对齐 docs/EPISODE_RULES.md） */
import { useState } from 'react'
import Modal from '../ui/Modal'
import {
  SEGMENT_DURATION_MAX,
  SEGMENT_DURATION_MIN,
  SHOT_DURATION_MAX,
} from '../../lib/segmentDuration'
import {
  DIALOGUE_PREFIX,
  DRAMA_NARRATION_PREFIX,
  DRAMA_SUBTITLE_CUE,
  VISUAL_PREFIX,
} from '../../lib/dramaEpisodeScriptValidate'

type Tab = 'payload' | 'script' | 'usage'

type Props = {
  open: boolean
  onClose: () => void
}

// 渲染 Seedance 规则说明弹窗
export function SeedanceRulesModal({ open, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('payload')

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Seedance 传值与使用规则"
      size="lg"
      className="pf-help-modal seedance-rules-modal"
      footer={
        <button type="button" className="pf-btn pf-btn-lime pf-btn-sm" onClick={onClose}>
          知道了
        </button>
      }
    >
      <div className="pf-help">
        <p className="pf-help-lede">
          分镜视频由 Seedance 多模态接口生成。下方说明系统如何把脚本、资产与顶栏参数组装成请求，以及漫剧分集脚本写法（详见{' '}
          <code>docs/EPISODE_RULES.md</code>）。
        </p>

        <div className="pf-help-tabs" role="tablist" aria-label="Seedance 规则分类">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'payload'}
            className={tab === 'payload' ? 'active' : undefined}
            onClick={() => setTab('payload')}
          >
            传值规则
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'script'}
            className={tab === 'script' ? 'active' : undefined}
            onClick={() => setTab('script')}
          >
            脚本写法
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'usage'}
            className={tab === 'usage' ? 'active' : undefined}
            onClick={() => setTab('usage')}
          >
            使用建议
          </button>
        </div>

        {tab === 'payload' ? (
          <div className="seedance-rules-section">
            <h4>顶栏参数 → API 字段</h4>
            <ul className="seedance-rules-list">
              <li>
                <strong>模型</strong> → <code>model</code>（Seedance 2.5 / 1.5）
              </li>
              <li>
                <strong>画幅 · 清晰度</strong>（分集顶栏设置）→ <code>ratio</code>、<code>resolution</code>
              </li>
              <li>
                <strong>时长</strong> → <code>duration</code>：脚本内{' '}
                <code>@duration</code> 合计（建议 4–{SHOT_DURATION_MAX} 秒）；无标签时用本镜「时长」字段
              </li>
              <li>
                <strong>视频风格</strong> → 写入提示词「画面风格」强制约束块
              </li>
            </ul>

            <h4>content 多模态数组（按顺序提交）</h4>
            <ol className="seedance-rules-list">
              <li>
                <strong>text</strong>：自动组装的完整提示词（见下方各约束块 + 正文）
              </li>
              <li>
                <strong>reference_image</strong>：本镜引用角色 / 场景 / 道具的封面或主图
              </li>
              <li>
                <strong>reference_audio</strong>：已绑定音色的角色与旁白试听音频
              </li>
            </ol>
            <p className="seedance-rules-note">
              系统默认开启 <code>generate_audio</code>：有口播意图时 Seedance 原生配音并烧录字幕；纯画面镜仅环境音、不烧字幕。
            </p>

            <h4>提示词自动组装顺序</h4>
            <ol className="seedance-rules-list">
              <li>【强制约束：视频画面风格】— 项目所选画风描述</li>
              <li>【强制约束：音频、字幕与配乐】— 根据脚本旁白 / 对白 / 画面 cue 推断</li>
              <li>【强制约束：角色音色】— 角色名 → 参考音频序号</li>
              <li>【强制约束：旁白音色】— 旁白 → 参考音频序号</li>
              <li>【强制约束：角色形象】— 角色名 → 参考图序号</li>
              <li>【强制约束：场景】— 场景名 → 参考图序号</li>
              <li>
                正文：将 <code>@asset:ID</code> 替换为「名称（参考图 N）」；将{' '}
                <code>@duration:N</code> 替换为时间区间（如 00:00-00:04）
              </li>
            </ol>
          </div>
        ) : null}

        {tab === 'script' ? (
          <div className="seedance-rules-section">
            <h4>时长标签</h4>
            <ul className="seedance-rules-list">
              <li>
                <code>@duration:N</code>：标记一段内容的时长（秒），单段建议{' '}
                {SEGMENT_DURATION_MIN}–{SEGMENT_DURATION_MAX} 秒
              </li>
              <li>
                一镜内所有 <code>@duration</code> 合计不超过 {SHOT_DURATION_MAX} 秒
              </li>
              <li>键入 <code>@</code> 可插入时长 chip 或引用资产</li>
            </ul>

            <h4>资产引用</h4>
            <ul className="seedance-rules-list">
              <li>
                <code>@asset:123</code>：在正文中引用 ID 为 123 的角色 / 场景 / 道具
              </li>
              <li>左侧资产面板点击资产，或本镜「参与资产」条，也会自动写入引用</li>
              <li>被引用的角色需有参考图；需口播的角色需绑定音色（参考音频）</li>
            </ul>

            <h4>漫剧常用 cue（勿用科普版「全程旁白烧录」字幕句）</h4>
            <div className="seedance-rules-examples">
              <code>{DRAMA_SUBTITLE_CUE}</code>
              <code>【BGM：低沉史诗，音量低于人声】</code>
              <code>@duration:4</code>
              <code>{VISUAL_PREFIX}空镜：浑浊黄河拍击老石……</code>
              <code>@duration:6</code>
              <code>{DIALOGUE_PREFIX}禹：水患未平，岂能退！</code>
              <code>{DRAMA_NARRATION_PREFIX}千年后，人们仍记得这一战。</code>
            </div>
            <ul className="seedance-rules-list">
              <li>
                <strong>空镜 / 景别</strong>：写成「空镜：…」「远景：…」「特写：…」或{' '}
                <code>{VISUAL_PREFIX}</code>；<strong>禁止</strong>标成对白/旁白（会口播并烧字幕）
              </li>
              <li>
                <strong>对白</strong>：<code>角色名：台词</code> 或 {DIALOGUE_PREFIX}
              </li>
              <li>
                <strong>旁白</strong>：{DRAMA_NARRATION_PREFIX}；字幕逐句轮换、与当前口播句同步，禁止整段叠满屏幕
              </li>
              <li>
                <strong>人物介绍</strong>：本剧首次出场重要角色叠字贴在<strong>该角色身旁</strong>（非底部字幕、非居中大标题）
              </li>
              <li>
                <strong>BGM</strong>：音量低于人声，不抢戏
              </li>
            </ul>

            <h4>景别 / 运镜（@ → 小工具）</h4>
            <ul className="seedance-rules-list">
              <li>
                编辑器键入 <code>@</code> →「小工具」→「景别 / 运镜」，可一键插入「空镜：」「特写：」「推镜：」等前缀
              </li>
              <li>公式：主体 + 动作 + 场景 +（景别/运镜）+（光影）；每段运动轴建议 ≤ 2</li>
              <li>近景大旋转易崩脸，环绕留给中景以上</li>
            </ul>
          </div>
        ) : null}

        {tab === 'usage' ? (
          <div className="seedance-rules-section">
            <h4>生成前检查</h4>
            <ul className="seedance-rules-list">
              <li>脚本校验：时长合法；空镜未被标成对白/旁白（编辑区会即时提示，有错误不可生成）</li>
              <li>本镜「参与资产」中的角色已有参考图；需说话的角色已「生成音色」或绑定试听（缺项会警告）</li>
              <li>项目顶栏确认画幅与清晰度；分集顶栏确认视频风格、模型后再点「生成」</li>
            </ul>

            <h4>队列与并行</h4>
            <ul className="seedance-rules-list">
              <li>分镜视频走独立 video 队列，Seedance 最多 10 路并行</li>
              <li>某一镜生成中时，仍可编辑其他镜脚本、预览已完成的视频</li>
              <li>「一键生成」会为本集各镜依次入队；单镜「生成」仅提交当前镜</li>
            </ul>

            <h4>镜间尾帧衔接</h4>
            <ul className="seedance-rules-list">
              <li>
                生成时默认 <code>return_last_frame=true</code>，成功后把尾帧写入分镜{' '}
                <code>params.lastFrameUrl</code>
              </li>
              <li>
                分集顶栏「镜间衔接」开启时：若本镜有角色/场景参考图或音色，
                尾帧以 <code>reference_image</code> 附在末尾（Seedance 禁止与 <code>first_frame</code> 混用）；
                无参考媒体时才用 <code>first_frame</code>
              </li>
              <li>
                普通生成请勿在脚本里写「编辑 / 延长」类措辞，以免任务被重分类；真正的「延长路径」仍未产品化
              </li>
            </ul>

            <h4>音色与参考音频</h4>
            <ul className="seedance-rules-list">
              <li>角色 / 旁白音色试听会作为 reference_audio 提交，保证口播声线一致</li>
              <li>参考音频合成后自动截到 15 秒内（API 单条上限约 30 秒）</li>
              <li>缺少参考图时，系统会尝试自动补图后再提交 Seedance</li>
            </ul>

            <h4>AI 重新分镜</h4>
            <p className="seedance-rules-note">
              会按剧本与资产重新规划各镜脚本与 @duration 结构；进行中的视频生成需等待完成后再操作，以免状态冲突。空镜须用「空镜：…」等画面写法，勿写成对白。
            </p>

          </div>
        ) : null}
      </div>
    </Modal>
  )
}
