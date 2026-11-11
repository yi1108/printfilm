import { useEffect, useState } from 'react'
import { printfilmStudioApi } from '../api'

export async function readProjectMedia(url: string, projectId?: number, assetId?: number, signal?: AbortSignal): Promise<Blob> {
  if (projectId) return printfilmStudioApi.readMedia(projectId, assetId && Number.isSafeInteger(assetId) ? assetId : 0, signal, url)
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error('源媒体无法读取')
  if (Number(response.headers.get('content-length')) > 100 * 1024 * 1024) throw new Error('源媒体不能超过 100MB')
  const blob = await response.blob()
  if (blob.size > 100 * 1024 * 1024) throw new Error('源媒体不能超过 100MB')
  return blob
}

export function useReadableMedia(url: string, projectId?: number, assetId?: number) {
  const [value, setValue] = useState(''), [error, setError] = useState('')
  useEffect(() => {
    const abort = new AbortController(); let objectUrl = ''
    setValue(''); setError('')
    void readProjectMedia(url, projectId, assetId, abort.signal).then((blob) => { if (!abort.signal.aborted) { objectUrl = URL.createObjectURL(blob); setValue(objectUrl) } }).catch((reason) => { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '素材读取失败') })
    return () => { abort.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [url, projectId, assetId])
  return { url: value, error }
}

export async function withProjectMedia<T>(urls: string[], projectId: number, operation: (urls: string[]) => Promise<T>): Promise<T> {
  const local: string[] = []; let size = 0
  try {
    for (const url of urls) { const blob = await readProjectMedia(url, projectId); size += blob.size; if (size > 200 * 1024 * 1024) throw new Error('本次处理的素材合计不能超过 200MB'); local.push(URL.createObjectURL(blob)) }
    return await operation(local)
  } finally { local.forEach((url) => URL.revokeObjectURL(url)) }
}
