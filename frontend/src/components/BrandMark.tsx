import { Link } from 'react-router-dom'

type Props = {
  to?: string
}

export default function BrandMark({ to = '/' }: Props) {
  return (
    <Link to={to} className="brand-mark">
      <img src="/logo.svg" alt="" className="brand-logo" width={28} height={28} />
      <span className="brand-word">PRINTFILM</span>
    </Link>
  )
}
