/** Legacy drama home — redirect to Agent entry. */
import { Navigate } from 'react-router-dom'

// Soft entry: /drama now serves DramaListPage via App routes; keep this for old imports
export default function DramaHomePage() {
  return <Navigate to="/drama" replace />
}
