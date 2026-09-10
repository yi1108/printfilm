import type { ReactNode } from 'react'

type IconProps = {
  size?: number
  className?: string
}

function Svg({ size = 18, className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      {children}
    </svg>
  )
}

export function IconGift(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="8" width="18" height="13" rx="2" />
      <path d="M12 8v13M3 12h18M12 8c0-2.2 1.2-4 3-4s3 .9 3 3-3 1-6 1-6-.1-6-1 1.2-3 3-3 3 1.8 3 4z" />
    </Svg>
  )
}

export function IconHelp(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.7 2.2c-.8.5-1.2 1-1.2 2v.3" />
      <circle cx="12" cy="17" r="0.8" fill="currentColor" stroke="none" />
    </Svg>
  )
}

export function IconBell(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M6 9a6 6 0 1 1 12 0c0 3.5 1.5 5 2 6H4c.5-1 2-2.5 2-6z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </Svg>
  )
}

export function IconChevronLeft(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M15 6l-6 6 6 6" />
    </Svg>
  )
}

export function IconPlay(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 6.5v11l9-5.5-9-5.5z" fill="currentColor" stroke="none" />
    </Svg>
  )
}

export function IconSliders(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M8 14v6" />
    </Svg>
  )
}

export function IconRefresh(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M20 6v5h-5" />
      <path d="M4 18v-5h5" />
      <path d="M18.5 11A7 7 0 0 0 7 7.5L4 11M5.5 13A7 7 0 0 0 17 16.5L20 13" />
    </Svg>
  )
}

export function IconMonitor(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="4" width="18" height="13" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </Svg>
  )
}

export function IconEdit(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 20h4l10-10-4-4L4 16v4z" />
      <path d="M13 7l4 4" />
    </Svg>
  )
}

export function IconDownload(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />
    </Svg>
  )
}

export function IconPlus(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  )
}

export function IconTrash(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 7h16M9 7V5h6v2M8 7l1 12h6l1-12" />
    </Svg>
  )
}

export function IconImage(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <circle cx="9" cy="10" r="1.5" />
      <path d="M3 15l5-4 4 3 3-2 6 5" />
    </Svg>
  )
}

export function IconCheck(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M5 12l5 5L20 7" />
    </Svg>
  )
}

export function IconEye(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="2.5" />
    </Svg>
  )
}

export function IconCopy(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M6 16H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </Svg>
  )
}

export function IconLink(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.2 1.2" />
      <path d="M14 11a5 5 0 0 0-7.1 0l-2 2a5 5 0 0 0 7.1 7.1l1.2-1.2" />
    </Svg>
  )
}

export function IconQr(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h2v2h-2zM18 14h2v2h-2zM14 18h2v2h-2zM18 18h2v2h-2z" />
    </Svg>
  )
}

export function IconCode(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 5l-2 14" />
    </Svg>
  )
}

export function IconSearch(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </Svg>
  )
}

export function IconClapper(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3 9h18v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9z" />
      <path d="M3 9l3.5-5 3 5 3-5 3 5 3-5L21 9" />
    </Svg>
  )
}

export function IconClock(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Svg>
  )
}

export function IconSend(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 12l16-7-7 16-2.5-6.5L4 12z" />
    </Svg>
  )
}

export function IconSparkles(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M12 3l1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2L12 3z" />
      <path d="M5 14l.7 2.1L8 17l-2.3.7L5 20l-.7-2.3L2 17l2.3-.9L5 14z" />
      <path d="M18 13l.6 1.8L20.5 15.5l-1.9.6L18 18l-.6-1.9L15.5 15.5l1.9-.7L18 13z" />
    </Svg>
  )
}
