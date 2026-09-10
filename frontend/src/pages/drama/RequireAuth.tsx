/** Require login for drama routes; redirect to /auth when missing token. */
import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

export default function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const token = localStorage.getItem('token')
  if (!token) {
    return <Navigate to="/auth" replace state={{ from: location.pathname }} />
  }
  return children
}
